from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

from agent.rag.config import RagConfig
from agent.state import OverallState
from agent.node.node_logging import log_node_runtime
from agent.tools.archive_tools import save_generated_artifact, save_question_set_json
from agent.tools.course_resource_tools import load_chapter_asset_bundle, load_manual_lecture, load_reference_quiz
from agent.tools.profile_tools import load_profile_context
from agent.tools.qa_tools import create_qa_session, save_qa_message


load_dotenv(override=True)

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "profiles" / "default_profile.md"
_personalization_model: Any | None = None


@log_node_runtime("personalization_node")
def personalization_node(state: OverallState) -> OverallState:
    if state.get("pipeline_type") == "progress" and isinstance(state.get("progress_patch_materials"), dict):
        from agent.node.knowledge_generation.progress_branch_nodes import build_progress_personalization_update

        return build_progress_personalization_update(state)

    course_resource_update = _course_resource_update_from_state(state)
    effective_state: OverallState = dict(state)
    effective_state.update(course_resource_update)
    profile_md_ref, profile_md_content = _profile_markdown_from_state(state)
    profile = _parse_profile_md(profile_md_content)
    materials = _generated_materials(effective_state)
    if materials:
        return _personalize_materials_update(
            effective_state,
            materials=materials,
            profile=profile,
            profile_loaded=bool(profile_md_content),
            profile_md_ref=profile_md_ref,
            profile_md_content=profile_md_content,
            course_resource_update=course_resource_update,
        )

    draft_output = _draft_output(effective_state)
    final_output, llm_raw_output = _personalize_output(
        effective_state,
        draft_output,
        profile=profile,
        profile_loaded=bool(profile_md_content),
        profile_md_ref=profile_md_ref,
    )

    update: OverallState = {
        "profile_md_ref": str(profile_md_ref),
        "profile_md_content": profile_md_content or "",
        "personalized_output": final_output,
        "final_output": final_output,
        "personalization_llm_raw_outputs": {"single": llm_raw_output} if llm_raw_output else {},
        "profile_update_suggestions": _default_profile_update_suggestions(state),
    }
    update.update(course_resource_update)
    return update


def _personalize_materials_update(
    state: OverallState,
    *,
    materials: dict[str, dict[str, Any]],
    profile: dict[str, str],
    profile_loaded: bool,
    profile_md_ref: Path,
    profile_md_content: str | None,
    course_resource_update: dict[str, Any] | None = None,
) -> OverallState:
    final_materials: dict[str, Any] = {}
    llm_raw_outputs: dict[str, str] = {}
    update: OverallState = {
        "profile_md_ref": str(profile_md_ref),
        "profile_md_content": profile_md_content or "",
        "profile_update_suggestions": _default_profile_update_suggestions(state),
    }
    if course_resource_update:
        update.update(course_resource_update)
    for kind, material in materials.items():
        if kind in _locked_material_types(state):
            personalized = material
            llm_raw_output = ""
        else:
            personalized, llm_raw_output = _personalize_output(
                state,
                material,
                profile=profile,
                profile_loaded=profile_loaded,
                profile_md_ref=profile_md_ref,
            )
        final_materials[kind] = personalized
        if llm_raw_output:
            llm_raw_outputs[kind] = llm_raw_output
        update.update(_type_specific_personalized_update(kind, personalized))

    update["final_materials"] = final_materials
    update["personalization_llm_raw_outputs"] = llm_raw_outputs
    update["personalized_output"] = {
        "meta": {
            "status": "success",
            "personalization": {
                "profile_loaded": profile_loaded,
                "profile_source": str(profile_md_ref),
                "strategy": "llm_personalization" if llm_raw_outputs else "expression_only",
            },
        },
        "learning_stage": state.get("learning_stage") or {},
        "materials": final_materials,
    }
    update["final_output"] = update["personalized_output"]
    return update


def _locked_material_types(state: OverallState) -> set[str]:
    value = state.get("personalization_locked_material_types")
    return {str(item) for item in value} if isinstance(value, list) else set()


def _generated_materials(state: OverallState) -> dict[str, dict[str, Any]]:
    value = state.get("generated_materials")
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, dict)}


def _type_specific_personalized_update(kind: str, output: dict[str, Any]) -> OverallState:
    mapping = {
        "lecture": "personalized_lecture_output",
        "practice": "personalized_practice_guide_output",
        "quiz": "personalized_question_output",
        "qa": "personalized_qa_output",
    }
    field_name = mapping.get(kind)
    return {field_name: output} if field_name else {}


def _persist_personalized_outputs(state: OverallState, outputs: dict[str, dict[str, Any]]) -> OverallState:
    if not (state.get("user_id") or state.get("_storage_root")):
        return {}

    saved_outputs: dict[str, Any] = {}
    update: OverallState = {}
    for kind, output in outputs.items():
        content_type = _normalized_content_type(kind, output, state)
        if content_type in {"lecture", "practice"}:
            saved = _save_markdown_material(state, output, content_type=content_type)
            saved_outputs[content_type] = saved
            update.update(_saved_material_update(content_type, saved))
        elif content_type in {"quiz", "question", "questions"}:
            saved = _save_question_material(state, output)
            saved_outputs["quiz"] = saved
            update.update(_saved_material_update("quiz", saved))
        elif content_type in {"qa", "qa_answer"}:
            saved = _save_qa_material(state, output)
            saved_outputs["qa"] = saved
            update.update(_saved_material_update("qa", saved))

    if saved_outputs:
        update["saved_outputs"] = saved_outputs
    return update


def _normalized_content_type(kind: str, output: dict[str, Any], state: OverallState) -> str:
    if kind != "single":
        return "practice" if kind == "practice_guide" else kind
    meta = output.get("meta")
    if isinstance(meta, dict) and meta.get("content_type"):
        return str(meta["content_type"])
    content_type = str(state.get("content_type") or "")
    return "practice" if content_type == "practice_guide" else content_type


def _save_markdown_material(state: OverallState, output: dict[str, Any], *, content_type: str) -> dict[str, Any]:
    artifact_type = "practice_guide" if content_type == "practice" else content_type
    return save_generated_artifact(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or ""),
        artifact_type=artifact_type,
        title=str(output.get("title") or artifact_type),
        markdown_content=_markdown_for_output(output),
        export_formats=[],
        metadata=_artifact_metadata(state, output),
        storage_root=state.get("_storage_root"),
    )


def _save_question_material(state: OverallState, output: dict[str, Any]) -> dict[str, Any]:
    payload = output.get("payload")
    questions = payload.get("questions") if isinstance(payload, dict) else []
    return save_question_set_json(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or ""),
        title=str(output.get("title") or "questions"),
        questions=[item for item in questions if isinstance(item, dict)] if isinstance(questions, list) else [],
        metadata=_artifact_metadata(state, output),
        storage_root=state.get("_storage_root"),
    )


def _save_qa_material(state: OverallState, output: dict[str, Any]) -> dict[str, Any]:
    user_id = str(state.get("user_id") or "default_user")
    session_id = str(state.get("qa_session_id") or "").strip()
    if not session_id:
        session = create_qa_session(
            user_id=user_id,
            course_id=str(state.get("course_id") or ""),
            title=str(output.get("title") or "QA conversation"),
            storage_root=state.get("_storage_root"),
        )
        session_id = str(session["session_id"])

    payload = output.get("payload") if isinstance(output.get("payload"), dict) else {}
    question = str(payload.get("question") or state.get("raw_prompt") or "").strip()
    answer = str(payload.get("answer") or output.get("summary") or "").strip()
    saved_messages = []
    if question:
        saved_messages.append(
            save_qa_message(
                session_id=session_id,
                user_id=user_id,
                role="user",
                content=question,
                metadata={"request_id": str(state.get("request_id") or "")},
                storage_root=state.get("_storage_root"),
            )
        )
    if answer:
        saved_messages.append(
            save_qa_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=answer,
                metadata={"request_id": str(state.get("request_id") or ""), "source": "personalization_node"},
                storage_root=state.get("_storage_root"),
            )
        )
    return {
        "session_id": session_id,
        "message_count": len(saved_messages),
        "messages": saved_messages,
        "paths": {
            "manifest": f"users/{_safe_user_id(user_id)}/conversations/{session_id}/manifest.json",
            "messages": f"users/{_safe_user_id(user_id)}/conversations/{session_id}/messages.jsonl",
            "transcript": f"users/{_safe_user_id(user_id)}/conversations/{session_id}/transcript.md",
        },
    }


def _saved_material_update(content_type: str, saved: dict[str, Any]) -> OverallState:
    if content_type == "lecture":
        paths = _markdown_artifact_paths(saved)
        return {
            "lecture_artifact_id": str(saved.get("artifact_id") or ""),
            "lecture_artifact_paths": paths,
            "saved_lecture_artifact": saved,
            "artifact_id": str(saved.get("artifact_id") or ""),
            "artifact_paths": paths,
            "saved_artifact": saved,
        }
    if content_type == "practice":
        paths = _markdown_artifact_paths(saved)
        return {
            "practice_guide_artifact_id": str(saved.get("artifact_id") or ""),
            "practice_guide_artifact_paths": paths,
            "saved_practice_guide_artifact": saved,
            "artifact_id": str(saved.get("artifact_id") or ""),
            "artifact_paths": paths,
            "saved_artifact": saved,
        }
    if content_type == "quiz":
        return {
            "question_artifact_id": str(saved.get("artifact_id") or ""),
            "question_artifact_paths": {"questions": str(saved.get("questions_path") or "")},
            "saved_question_artifact": saved,
            "artifact_id": str(saved.get("artifact_id") or ""),
            "artifact_paths": {"questions": str(saved.get("questions_path") or "")},
            "saved_artifact": saved,
        }
    if content_type == "qa":
        return {
            "qa_session_id": str(saved.get("session_id") or ""),
            "qa_artifact_paths": saved.get("paths") or {},
            "saved_qa_artifact": saved,
        }
    return {}


def _markdown_artifact_paths(saved: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {"markdown": str(saved.get("markdown_path") or "")}
    assets = saved.get("markdown_assets")
    if isinstance(assets, list) and assets:
        paths["assets"] = [str(item) for item in assets if str(item).strip()]
    return paths


def _artifact_metadata(state: OverallState, output: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": str(state.get("course_id") or ""),
        "chapter_id": str(state.get("chapter_id") or ""),
        "content_type": _content_type_from_output(output),
        "markdown_asset_roots": _markdown_asset_roots(state),
        "source": output,
    }


def _markdown_asset_roots(state: OverallState) -> list[str]:
    roots: list[str] = []
    bundle = state.get("course_resource_bundle")
    if isinstance(bundle, dict) and bundle.get("chapter_path"):
        roots.append(str(bundle["chapter_path"]))
    paths = state.get("chapter_resource_paths")
    if isinstance(paths, dict):
        for value in paths.values():
            path = Path(str(value))
            if path.suffix:
                roots.append(str(path.parent))
            else:
                roots.append(str(path))
    return list(dict.fromkeys(item for item in roots if item.strip()))


def _markdown_for_output(output: dict[str, Any]) -> str:
    title = str(output.get("title") or "Generated Material")
    summary = str(output.get("summary") or "")
    payload = output.get("payload")
    base_content = str(output.get("base_content") or "").strip()
    if base_content:
        lines = [base_content, ""]
    else:
        lines = [f"# {title}", ""]
        if summary:
            lines.extend([summary, ""])
        if isinstance(payload, dict):
            _append_payload_markdown(lines, payload)
    patches = output.get("knowledge_gap_patches")
    if isinstance(patches, list):
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            content = str(patch.get("content") or "").strip()
            if not content:
                continue
            heading = str(patch.get("target_section") or "").strip()
            if heading:
                lines.extend([f"## {heading}", ""])
            lines.extend([content, ""])
    return "\n".join(lines).strip() + "\n"


def _append_payload_markdown(lines: list[str], payload: dict[str, Any]) -> None:
    sections = payload.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict):
                heading = str(section.get("heading") or "").strip()
                content = str(section.get("content") or "").strip()
                if heading and content:
                    lines.extend([f"## {heading}", "", content, ""])
        return
    for key, value in payload.items():
        if isinstance(value, list):
            lines.extend([f"## {key}", ""])
            for item in value:
                lines.append(f"- {item}" if not isinstance(item, dict) else f"- {json.dumps(item, ensure_ascii=False)}")
            lines.append("")
        elif value:
            lines.extend([f"## {key}", "", str(value), ""])


def _safe_user_id(user_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in user_id)


def _profile_markdown_from_state(state: OverallState) -> tuple[Path, str | None]:
    if state.get("_profile_path") or state.get("profile_md_ref"):
        profile_md_ref = _profile_ref(state)
        return profile_md_ref, _read_profile_md(profile_md_ref)

    user_id = str(state.get("user_id") or "").strip()
    if user_id:
        try:
            context = load_profile_context(user_id=user_id, storage_root=state.get("_storage_root"))
        except (OSError, ValueError):
            context = {}
        profile_md_ref = Path(str(context.get("profile_md_ref") or DEFAULT_PROFILE_PATH))
        profile_md_content = context.get("profile_md_content")
        return profile_md_ref, str(profile_md_content) if profile_md_content is not None else None

    profile_md_ref = _profile_ref(state)
    return profile_md_ref, _read_profile_md(profile_md_ref)


def _profile_ref(state: OverallState) -> Path:
    configured = state.get("_profile_path") or state.get("profile_md_ref")
    if configured:
        text = str(configured).strip()
        if text.startswith("file://"):
            return Path(text.removeprefix("file://")).expanduser()
        return Path(text).expanduser()
    return DEFAULT_PROFILE_PATH


def _read_profile_md(profile_path: Path) -> str | None:
    try:
        if profile_path.exists() and profile_path.is_file():
            return profile_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


def _draft_output(state: OverallState) -> dict[str, Any]:
    value = state.get("generated_content") or state.get("final_output") or {}
    return deepcopy(value) if isinstance(value, dict) else {}


def _personalize_output(
    state: OverallState,
    output: dict[str, Any],
    *,
    profile: dict[str, str],
    profile_loaded: bool,
    profile_md_ref: Path,
) -> tuple[dict[str, Any], str]:
    personalized = deepcopy(output)
    llm_raw_output = ""
    llm_output = _invoke_personalization_llm(
        state,
        build_personalization_prompt(
            state,
            output=output,
            profile_md_content=state.get("profile_md_content") or _profile_text_from_dict(profile),
        ),
    )
    if llm_output:
        llm_raw_output = llm_output["raw"]
        personalized = _merge_llm_personalization(personalized, llm_output["data"])

    meta = personalized.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["personalization"] = {
            "profile_loaded": profile_loaded,
            "profile_source": str(profile_md_ref),
            "strategy": "llm_personalization" if llm_raw_output else "expression_only",
        }

    if not llm_raw_output:
        summary = str(personalized.get("summary") or "")
        personalized["summary"] = _personalize_summary(summary, profile, profile_loaded)
        personalized["next_actions"] = _personalized_next_actions(personalized.get("next_actions"))
        personalized["learning_guidance"] = _learning_guidance(profile, profile_loaded)
    else:
        personalized["next_actions"] = _dedupe_nonempty(
            [str(item) for item in personalized.get("next_actions") or []]
        )
        personalized.setdefault("learning_guidance", _learning_guidance(profile, profile_loaded))
    return personalized, llm_raw_output


def build_personalization_prompt(
    state: OverallState,
    *,
    output: dict[str, Any],
    profile_md_content: str,
) -> str:
    return f"""
你是 DeepTutor 的个性化输出节点。请根据用户画像 Markdown 和已经生成的学习材料，重写为更适合该用户阅读的最终输出。

要求:
- 只能调整表达方式、讲解顺序、学习提示和练习建议，不要新增未经材料支持的事实。
- 必须保留原材料中的关键信息和安全边界。
- 不要删除题目答案、解析、实训安全要点或 QA 的直接回答。
- 根据内容类型分别处理 lecture、practice、quiz、qa。
- 只返回 JSON，不要 Markdown，不要解释。

JSON 格式:
{{
  "title": "个性化后的标题",
  "summary": "个性化后的摘要",
  "payload": {{}},
  "next_actions": ["下一步建议"],
  "learning_guidance": {{
    "profile_loaded": true,
    "preference": "识别到的学习偏好",
    "weak_points": ["薄弱点"],
    "personalization_scope": "说明本次只做表达层个性化"
  }}
}}

task:
{state.get("task") or ""}

content_type:
{state.get("content_type") or _content_type_from_output(output)}

user_profile_markdown:
{profile_md_content}

course_resource_reference:
{_course_resource_prompt_context(state)}

material_json:
{json.dumps(output, ensure_ascii=False)}
""".strip()


def _course_resource_update_from_state(state: OverallState) -> dict[str, Any]:
    course_id = str(state.get("course_id") or "").strip()
    chapter_id = str(state.get("chapter_id") or "").strip()
    if not course_id or not chapter_id:
        return {}

    resource_root = state.get("_course_resource_root")
    update: dict[str, Any] = {}
    try:
        bundle = load_chapter_asset_bundle(course_id, chapter_id, resource_root=resource_root)
    except (OSError, KeyError, ValueError):
        return {}

    update["course_resource_bundle"] = bundle
    try:
        update["manual_lecture_content"] = load_manual_lecture(
            course_id,
            chapter_id,
            resource_root=resource_root,
        )["content"]
    except (OSError, KeyError, ValueError):
        pass
    try:
        update["reference_quiz"] = load_reference_quiz(course_id, chapter_id, resource_root=resource_root)
    except (OSError, KeyError, ValueError):
        pass
    return update


def _course_resource_prompt_context(state: OverallState) -> str:
    parts: list[str] = []
    manual_lecture = str(state.get("manual_lecture_content") or "").strip()
    if manual_lecture:
        parts.extend(["manual_lecture:", manual_lecture])

    reference_quiz = state.get("reference_quiz")
    if isinstance(reference_quiz, dict) and reference_quiz:
        quiz_summary = {
            "question_count": len(reference_quiz.get("questions") or []),
            "questions": reference_quiz.get("questions") or [],
        }
        parts.extend(["reference_quiz:", json.dumps(quiz_summary, ensure_ascii=False)])

    bundle = state.get("course_resource_bundle")
    if isinstance(bundle, dict) and bundle:
        bundle_summary = {
            "chapter_id": bundle.get("chapter_id"),
            "title": bundle.get("title"),
            "asset_types": list((bundle.get("assets") or {}).keys()) if isinstance(bundle.get("assets"), dict) else [],
        }
        parts.extend(["course_bundle:", json.dumps(bundle_summary, ensure_ascii=False)])
    return "\n".join(parts) if parts else "未加载课程标准资料。"


def _personalize_summary(summary: str, profile: dict[str, str], profile_loaded: bool) -> str:
    preference = profile.get("学习偏好") or profile.get("preference") or "步骤化、少术语"
    suffix = "已按本地画像 Markdown 进行表达层个性化整理" if profile_loaded else "已按默认个性化规则整理"
    if summary:
        return f"{summary}（{preference}；{suffix}）"
    return f"{preference}；{suffix}。"


def _invoke_personalization_llm(state: OverallState, prompt: str) -> dict[str, Any]:
    try:
        response = _model_from_state(state).invoke([_human_message(prompt)])
    except ModuleNotFoundError:
        return {}
    raw = str(response.content)
    data = _load_json_object(raw)
    return {"raw": raw, "data": data} if data else {}


def _model_from_state(state: OverallState) -> Any:
    return state.get("_personalization_model") or state.get("_generation_model") or state.get("_model") or _default_model()


def _default_model() -> Any:
    global _personalization_model
    if _personalization_model is None:
        from langchain_deepseek import ChatDeepSeek

        _personalization_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
    return _personalization_model


def _human_message(content: str) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(str(text).strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _merge_llm_personalization(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key in ("title", "summary"):
        value = _clean_string(data.get(key))
        if value:
            merged[key] = value
    payload = data.get("payload")
    if isinstance(payload, dict) and payload:
        merged["payload"] = deepcopy(payload)
    next_actions = _clean_string_list(data.get("next_actions"))
    if next_actions:
        merged["next_actions"] = next_actions
    learning_guidance = data.get("learning_guidance")
    if isinstance(learning_guidance, dict):
        merged["learning_guidance"] = deepcopy(learning_guidance)
    return merged


def _content_type_from_output(output: dict[str, Any]) -> str:
    meta = output.get("meta")
    if isinstance(meta, dict):
        return str(meta.get("content_type") or "")
    return ""


def _profile_text_from_dict(profile: dict[str, str]) -> str:
    if not profile:
        return ""
    return "\n".join(f"- {key}: {value}" for key, value in profile.items())


def _clean_string(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()) if isinstance(value, str) else ""


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_string(item) for item in value if _clean_string(item)]


def _personalized_next_actions(raw_actions: Any) -> list[str]:
    actions = [str(item) for item in raw_actions] if isinstance(raw_actions, list) else []
    filtered = [item for item in actions if "内容审查" not in item and "审查节点" not in item]
    filtered.append("DeepTutor 可根据 profile_update_suggestions 决定是否更新画像")
    return _dedupe_nonempty(filtered)


def _learning_guidance(profile: dict[str, str], profile_loaded: bool) -> dict[str, Any]:
    return {
        "profile_loaded": profile_loaded,
        "background": profile.get("专业背景") or profile.get("背景") or "",
        "preference": profile.get("学习偏好") or profile.get("preference") or "步骤化、少术语",
        "weak_points": _split_profile_value(profile.get("薄弱点") or profile.get("weak_points") or ""),
        "personalization_scope": "仅调整表达顺序、提示语和学习建议，不新增知识事实。",
    }


def _default_profile_update_suggestions(state: OverallState) -> dict[str, Any]:
    return {
        "md_patches": [],
        "observations": [
            {
                "type": "request_preference_signal",
                "value": str(state.get("content_type") or ""),
                "confidence": "low",
                "reason": "单次生成请求只能作为弱画像信号，暂不自动写回本地 Markdown。",
            }
        ],
    }


def _parse_profile_md(profile_md_content: str | None) -> dict[str, str]:
    profile: dict[str, str] = {}
    if not profile_md_content:
        return profile
    for line in profile_md_content.splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            key, separator, value = stripped.partition("：")
        if separator and key.strip() and value.strip():
            profile[key.strip()] = value.strip()
    return profile


def _split_profile_value(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("、", ",").replace("，", ",").split(",") if item.strip()]


def _dedupe_nonempty(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
