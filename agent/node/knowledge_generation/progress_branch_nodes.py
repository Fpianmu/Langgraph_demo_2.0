from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langgraph.types import Command

from agent.node.node_logging import log_node_runtime
from agent.rag.config import RagConfig
from agent.rag.schemas import RagPackage
from agent.rag.simple_retriever import SimpleResourceRetriever
from agent.state import OverallState
from agent.storage_layout import resolve_storage_root, safe_segment
from agent.tools.archive_tools import save_generated_artifact, save_question_set_json
from agent.tools.course_resource_tools import load_chapter_asset_bundle, load_reference_quiz
from agent.tools.profile_tools import load_profile_context
from agent.tools.profile.capability_profile_score import build_capability_profile_score, resource_difficulty_for
from agent.tools.profile_tools import record_resource_difficulty


_progress_model: Any | None = None

QUIZ_TYPE_POLICY: dict[str, float] = {
    "single_choice": 0.44,
    "true_false": 0.16,
    "cloze": 0.2,
    "short_answer": 0.2,
}

QUIZ_TYPE_ORDER = ["single_choice", "true_false", "cloze", "short_answer"]
QUIZ_CAPABILITY_DIMENSIONS = [
    "foundations",
    "safety",
    "process_planning",
    "programming",
    "machining_operation",
    "quality_control",
    "maintenance",
    "advanced_manufacturing",
]

RESOURCE_TYPE_LABELS = {
    "lecture": "讲义",
    "practice": "实训资料",
    "quiz": "测验",
}


@log_node_runtime("knowledge_gap_loader_node")
def knowledge_gap_loader_node(state: OverallState) -> OverallState:
    user_id = str(state.get("user_id") or "default_user")
    context = load_profile_context(user_id=user_id, storage_root=state.get("_storage_root"))
    files = context.get("knowledge_gap_files") if isinstance(context.get("knowledge_gap_files"), dict) else {}
    documents: dict[str, Any] = {"json": {}, "markdown": "", "events": []}
    if files:
        documents["json"] = _read_json_file(files.get("json"))
        documents["markdown"] = _read_text_file(files.get("markdown"))
        documents["events"] = _read_jsonl_file(files.get("events"))
    return {
        "profile_context": context,
        "profile_md_ref": str(context.get("profile_md_ref") or ""),
        "profile_md_content": str(context.get("profile_md_content") or ""),
        "knowledge_gap_files": {str(key): str(value) for key, value in files.items()},
        "knowledge_gap_documents": documents,
        "knowledge_gap_events": [item for item in documents["events"] if isinstance(item, dict)],
        "knowledge_gap_load_result": {
            "status": "success",
            "gap_count": len((documents.get("json") or {}).get("gaps") or []),
            "event_count": len(documents["events"]),
        },
    }


def _profile_context_from_state(state: OverallState) -> dict[str, Any]:
    context = state.get("profile_context") if isinstance(state.get("profile_context"), dict) else {}
    if context:
        return context
    user_id = str(state.get("user_id") or "default_user")
    return load_profile_context(user_id=user_id, storage_root=state.get("_storage_root"))


def _capability_profile_score_from_state(state: OverallState) -> dict[str, Any]:
    context = _profile_context_from_state(state)
    profile_score = context.get("capability_profile_score") if isinstance(context.get("capability_profile_score"), dict) else {}
    if profile_score:
        return profile_score
    assessment = context.get("capability_assessment") if isinstance(context.get("capability_assessment"), dict) else {}
    return build_capability_profile_score(assessment)


def _resource_difficulty_for_state(
    state: OverallState,
    resource_type: str,
    resource_id: str,
    *,
    source_node: str,
    resource_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_score = _capability_profile_score_from_state(state)
    return resource_difficulty_for(
        profile_score,
        resource_type=resource_type,
        resource_id=resource_id,
        chapter_id=str(state.get("chapter_id") or ""),
        source_node=source_node,
        resource_meta=resource_meta,
    )


def _record_resource_difficulty(state: OverallState, difficulty: dict[str, Any]) -> None:
    user_id = str(state.get("user_id") or "default_user")
    storage_root = state.get("_storage_root")
    try:
        record_resource_difficulty(user_id=user_id, record=difficulty, storage_root=storage_root)
    except Exception:
        pass


@log_node_runtime("gap_focus_analysis_node")
def gap_focus_analysis_node(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _gap_focus_prompt(state))
    data = _load_json_object(raw)
    related = _list_of_dicts(data.get("related_knowledge_gaps"))
    patch_targets = _list_of_dicts(data.get("patch_target_points"))
    quiz_focus = _list_of_dicts(data.get("quiz_relevant_focus_points"))
    if not data:
        related, patch_targets, quiz_focus = _fallback_gap_focus_analysis(state)
        data = {
            "related_knowledge_gaps": related,
            "patch_target_points": patch_targets,
            "quiz_relevant_focus_points": quiz_focus,
        }
    return {
        "gap_focus_analysis": data,
        "related_knowledge_gaps": related,
        "patch_target_points": patch_targets,
        "quiz_relevant_focus_points": quiz_focus,
        "knowledge_gap_patch_plan": {"patch_target_points": patch_targets},
        "gap_focus_analysis_raw_output": raw,
    }


@log_node_runtime("chapter_resource_loader_node")
def chapter_resource_loader_node(state: OverallState) -> OverallState:
    return _load_chapter_resource_context(state)


def _load_chapter_resource_context(state: OverallState) -> OverallState:
    course_id = str(state.get("course_id") or "cnc_lathe")
    chapter_id = str(state.get("chapter_id") or "").strip()
    resource_root = state.get("_course_resource_root")
    try:
        bundle = load_chapter_asset_bundle(course_id, chapter_id, resource_root=resource_root)
    except (OSError, KeyError, ValueError) as exc:
        return {
            "course_resource_bundle": {},
            "manual_lecture_content": "",
            "manual_practice_content": "",
            "reference_quiz": {},
            "chapter_base_materials": {"lecture": "", "practice": "", "reference_quiz": {}},
            "chapter_resource_paths": {},
            "chapter_resource_load_result": {
                "status": "missing",
                "reason": str(exc),
                "has_lecture": False,
                "has_practice": False,
                "has_reference_quiz": False,
            },
        }
    assets = bundle.get("assets") if isinstance(bundle.get("assets"), dict) else {}
    manual_lecture = _read_asset_content(((assets.get("lecture") or {}).get("manual_lecture")))
    manual_practice = _read_asset_content(((assets.get("practice") or {}).get("practice_manual")))
    reference_quiz: dict[str, Any] = {}
    try:
        reference_quiz = load_reference_quiz(course_id, chapter_id, resource_root=resource_root)
    except (OSError, KeyError, ValueError):
        reference_quiz = {}
    paths = _resource_paths_from_assets(assets)
    return {
        "course_resource_bundle": bundle,
        "manual_lecture_content": manual_lecture,
        "manual_practice_content": manual_practice,
        "reference_quiz": reference_quiz,
        "chapter_base_materials": {
            "lecture": manual_lecture,
            "practice": manual_practice,
            "reference_quiz": reference_quiz,
        },
        "chapter_resource_paths": paths,
        "chapter_resource_load_result": {
            "status": "success",
            "has_lecture": bool(manual_lecture),
            "has_practice": bool(manual_practice),
            "has_reference_quiz": bool(reference_quiz),
        },
    }


@log_node_runtime("quiz_adaptation_context_node")
def quiz_adaptation_context_node(state: OverallState) -> OverallState:
    profile = _profile_context_from_state(state)
    profile_score = _capability_profile_score_from_state(state)
    average_score = _average_profile_score(profile_score, profile)
    target = "easy" if average_score < 0.45 else "normal" if average_score < 0.75 else "hard"
    policy = {
        "target_difficulty": target,
        "easy_ratio": 0.5 if target == "easy" else 0.3 if target == "normal" else 0.2,
        "normal_ratio": 0.4 if target == "easy" else 0.5 if target == "normal" else 0.4,
        "hard_ratio": 0.1 if target == "easy" else 0.2 if target == "normal" else 0.4,
        "reason": "根据用户画像中的量化学习指标确定。",
    }
    return {
        "user_quantitative_profile": {
            "average_score": average_score,
            "capability_profile_score": profile_score,
            "learning_progress": state.get("learning_progress") or {},
        },
        "quiz_difficulty_policy": policy,
        "quiz_reference_examples": state.get("reference_quiz") if isinstance(state.get("reference_quiz"), dict) else {},
        "quiz_adaptation_result": {"status": "success", "target_difficulty": target},
    }


@log_node_runtime("quiz_context_adapter_node")
def quiz_context_adapter_node(state: OverallState) -> OverallState:
    rag_package = state.get("rag_package") if isinstance(state.get("rag_package"), dict) else {}
    task = str(state.get("quiz_generation_prompt") or state.get("task") or state.get("raw_prompt") or "").strip()
    resource_context = _load_chapter_resource_context(state)
    bundle = resource_context.get("course_resource_bundle")
    manifest = bundle.get("chapter_manifest") if isinstance(bundle, dict) else {}
    chapter_focus = manifest.get("focus") if isinstance(manifest, dict) else {}
    return {
        **resource_context,
        "chapter_focus": chapter_focus if isinstance(chapter_focus, dict) else {},
        "quiz_rag_package": rag_package,
        "quiz_rag_evidence": [item for item in rag_package.get("evidence") or [] if isinstance(item, dict)],
        "patch_rag_package": {},
        "patch_rag_evidence": [],
        "quiz_source_mode": "generated",
        "quiz_strategy": "generate",
        "quiz_context_adapter_result": {
            "status": "success",
            "source": "rag_package",
            "task": task,
            "has_quiz_rag": bool(rag_package),
            "has_chapter_resources": resource_context.get("chapter_resource_load_result", {}).get("status") == "success",
            "has_reference_quiz": bool(resource_context.get("reference_quiz")),
        },
    }


@log_node_runtime("quiz_blueprint_node")
def quiz_blueprint_node(state: OverallState) -> OverallState:
    ratio_policy = _quiz_blueprint_ratio_policy(state)
    question_count = _question_count_for_generation(state)
    target_counts = _target_counts_for_ratio(question_count, ratio_policy)
    related_gap_ids = _related_gap_ids(state)
    type_counts = _quiz_type_counts(question_count)
    slots = _quiz_blueprint_slots(
        question_count=question_count,
        type_counts=type_counts,
        purpose_counts=target_counts,
        difficulty_policy=state.get("quiz_difficulty_policy") if isinstance(state.get("quiz_difficulty_policy"), dict) else {},
        related_gap_ids=related_gap_ids,
    )
    blueprint = {
        "status": "success",
        "source": "quiz_blueprint_node",
        "question_count": question_count,
        "target_ratios": ratio_policy,
        "target_counts": target_counts,
        "type_policy": QUIZ_TYPE_POLICY,
        "type_counts": type_counts,
        "slots": slots,
        "related_gap_ids": related_gap_ids,
        "source_packages": {
            "chapter_core": {
                "rag_package_key": "quiz_rag_package",
                "evidence_count": _evidence_count(state.get("quiz_rag_package")),
            },
            "gap_remediation": {
                "rag_package_key": "patch_rag_package",
                "evidence_count": _evidence_count(state.get("patch_rag_package")),
            },
        },
        "required_question_fields": [
            "question_purpose",
            "knowledge_points",
            "core_exam_points",
            "related_gap_ids",
            "question_type",
            "reference_answer",
            "points",
            "capability_dimension",
        ],
        "chapter_focus_summary": str((state.get("chapter_focus") or {}).get("summary") or ""),
        "difficulty_policy": state.get("quiz_difficulty_policy") if isinstance(state.get("quiz_difficulty_policy"), dict) else {},
    }
    return {
        "quiz_generation_blueprint": blueprint,
        "quiz_blueprint_slots": slots,
        "quiz_type_policy": QUIZ_TYPE_POLICY,
        "quiz_blueprint_result": {
            "status": "success",
            "source": "quiz_blueprint_node",
            "question_count": question_count,
            "target_counts": target_counts,
            "type_counts": type_counts,
            "related_gap_count": len(related_gap_ids),
        },
    }


@log_node_runtime("quiz_blueprint_parser_node")
def quiz_blueprint_parser_node(state: OverallState) -> OverallState:
    user_blueprint = _user_quiz_blueprint_input(state)
    parsed = _parse_regular_quiz_blueprint(state, user_blueprint)
    return {
        "quiz_generation_blueprint": parsed["blueprint"],
        "quiz_blueprint_slots": parsed["slots"],
        "quiz_type_policy": parsed["type_policy"],
        "quiz_blueprint_parse_result": parsed["parse_result"],
        "quiz_blueprint_result": parsed["parse_result"],
    }


@log_node_runtime("quiz_strategy_node")
def quiz_strategy_node(state: OverallState) -> Command[str]:
    strategy = _quiz_strategy_for_state(state)
    target = "course_resource_quiz_selection_node" if strategy == "select_from_course_resource" else "progress_quiz_rag_node"
    source_mode = "course_resource_selection" if strategy == "select_from_course_resource" else "generated"
    return Command(
        update={
            "quiz_strategy": strategy,
            "quiz_source_mode": source_mode,
            "quiz_strategy_result": {
                "status": "success",
                "chapter_id": str(state.get("chapter_id") or ""),
                "strategy": strategy,
                "next_node": target,
            },
        },
        goto=target,
    )


@log_node_runtime("progress_rag_planner_node")
def progress_rag_planner_node(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _rag_planner_prompt(state))
    data = _load_json_object(raw)
    patch_queries = _clean_string_list(data.get("progress_patch_rag_queries"))
    quiz_queries = _clean_string_list(data.get("progress_quiz_rag_queries"))
    if not patch_queries:
        patch_queries = _fallback_patch_queries(state)
    if not quiz_queries:
        quiz_queries = _focus_queries(state, category="quiz") or _focus_queries(state)
    patch_queries = _without_query_overlap(patch_queries, quiz_queries)
    if not patch_queries:
        patch_queries = _without_query_overlap(_fallback_patch_queries(state), quiz_queries)
    return {
        "progress_patch_rag_queries": patch_queries,
        "progress_quiz_rag_queries": quiz_queries,
        "progress_rag_plan": {
            "patch_queries": patch_queries,
            "quiz_queries": quiz_queries,
            "raw_output": raw,
        },
    }


@log_node_runtime("progress_patch_rag_node")
def progress_patch_rag_node(state: OverallState) -> OverallState:
    package = _retrieve_package(state, state.get("progress_patch_rag_queries") or [])
    return {
        "patch_rag_package": package.model_dump(mode="json"),
        "patch_rag_evidence": [item.model_dump(mode="json") for item in package.evidence],
        "patch_rag_llm_raw_output": "",
    }


@log_node_runtime("progress_quiz_rag_node")
def progress_quiz_rag_node(state: OverallState) -> OverallState:
    package = _retrieve_package(state, state.get("progress_quiz_rag_queries") or [])
    return {
        "quiz_rag_package": package.model_dump(mode="json"),
        "quiz_rag_evidence": [item.model_dump(mode="json") for item in package.evidence],
        "quiz_rag_llm_raw_output": "",
    }


@log_node_runtime("progress_patch_generation_node")
def progress_patch_generation_node(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _patch_generation_prompt(state))
    data = _load_json_object(raw)
    lecture_patches = _list_of_dicts(data.get("lecture_patches"))
    practice_patches = _list_of_dicts(data.get("practice_patches"))
    if not lecture_patches and not practice_patches:
        lecture_patches = _fallback_lecture_patches(state)
    lecture_patch_content = {"patches": lecture_patches}
    practice_patch_content = {"patches": practice_patches}
    materials: dict[str, Any] = {}
    if "lecture" in (state.get("required_material_types") or []) and (
        state.get("manual_lecture_content") or lecture_patches
    ):
        materials["lecture"] = {
            "meta": {"content_type": "lecture", "status": "patch_ready"},
            "title": _title_for(state, "lecture"),
            "summary": "章节基础讲义，并附带清晰可见的知识漏洞补充。",
            "payload": {
                "base_content": state.get("manual_lecture_content") or "",
                "knowledge_gap_patches": lecture_patches,
            },
        }
    if "practice" in (state.get("required_material_types") or []) and (
        state.get("manual_practice_content") or practice_patches
    ):
        materials["practice"] = {
            "meta": {"content_type": "practice", "status": "patch_ready"},
            "title": _title_for(state, "practice"),
            "summary": "章节基础实训资料，并附带清晰可见的知识漏洞补充。",
            "payload": {
                "base_content": state.get("manual_practice_content") or "",
                "knowledge_gap_patches": practice_patches,
            },
        }
    resource_difficulties = {}
    for kind, material in materials.items():
        difficulty = _resource_difficulty_for_state(
            state,
            kind,
            f"{state.get('request_id') or state.get('chapter_id') or 'chapter'}:{kind}",
            source_node="progress_patch_generation_node",
            resource_meta={
                "title": str(material.get("title") or _title_for(state, kind)),
                "summary": str(material.get("summary") or ""),
            },
        )
        resource_difficulties[kind] = difficulty
        _record_resource_difficulty(state, difficulty)
        material.setdefault("meta", {})
        if isinstance(material.get("meta"), dict):
            material["meta"]["resource_difficulty"] = difficulty["resource_difficulty"]
            material["meta"]["profile_score"] = difficulty["profile_score"]
    return {
        "lecture_patch_content": lecture_patch_content,
        "practice_patch_content": practice_patch_content,
        "progress_patch_materials": materials,
        "generated_materials": materials,
        "resource_difficulty_records": resource_difficulties,
        "patch_generation_raw_output": raw,
    }


@log_node_runtime("progress_quiz_generation_node")
def progress_quiz_generation_node(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _quiz_generation_prompt(state))
    data = _load_json_object(raw)
    questions = _normalize_progress_questions(_list_of_dicts(data.get("questions")), state)
    if not questions:
        questions = _fallback_quiz_questions(state)
    output = {
        "meta": {"content_type": "quiz", "status": "success", "source": "progress_quiz_generation_node"},
        "title": str(data.get("title") or _title_for(state, "quiz")),
        "summary": str(data.get("summary") or "根据章节重点和参考例题生成的测试题。"),
        "questions": questions,
    }
    difficulty = _resource_difficulty_for_state(
        state,
        "quiz",
        f"{state.get('request_id') or state.get('chapter_id') or 'chapter'}:quiz",
        source_node="progress_quiz_generation_node",
        resource_meta={
            "title": str(output.get("title") or _title_for(state, "quiz")),
            "summary": str(output.get("summary") or ""),
            "question_count": len(questions),
        },
    )
    _record_resource_difficulty(state, difficulty)
    output["meta"]["resource_difficulty"] = difficulty["resource_difficulty"]
    output["meta"]["profile_score"] = difficulty["profile_score"]
    return {
        "progress_quiz_output": output,
        "resource_difficulty_records": {"quiz": difficulty},
        "progress_quiz_generation_raw_output": raw,
    }


@log_node_runtime("quiz_typed_generation_node")
def quiz_typed_generation_node(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _typed_quiz_generation_prompt(state))
    data = _load_json_object(raw)
    questions = _normalize_typed_questions(_list_of_dicts(data.get("questions")), state)
    if not questions:
        questions = _fallback_typed_quiz_questions(state)
    output = {
        "meta": {"content_type": "quiz", "status": "success", "source": "quiz_typed_generation_node"},
        "title": str(data.get("title") or _title_for(state, "quiz")),
        "summary": str(data.get("summary") or "根据测验蓝图生成的多题型测试题。"),
        "questions": questions,
    }
    return {
        "typed_quiz_output": output,
        "progress_quiz_output": output,
        "typed_quiz_generation_raw_output": raw,
        "progress_quiz_generation_raw_output": raw,
    }


@log_node_runtime("quiz_schema_normalizer_node")
def quiz_schema_normalizer_node(state: OverallState) -> OverallState:
    output = dict(state.get("typed_quiz_output") or state.get("progress_quiz_output") or {})
    raw_questions = output.get("questions") if isinstance(output.get("questions"), list) else []
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    slots = _quiz_slots_from_state(state)
    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict):
            errors.append({"sequence": index, "reason": "question_not_object"})
            continue
        slot = slots[index - 1] if index - 1 < len(slots) else {}
        question, question_errors = _normalize_question_for_schema(raw_question, slot, state, index)
        if question_errors:
            errors.extend(question_errors)
        normalized.append(question)
    if slots and len(normalized) != len(slots):
        errors.append(
            {
                "reason": "question_count_mismatch",
                "expected": len(slots),
                "actual": len(normalized),
            }
        )
    output["questions"] = normalized
    output["meta"] = {
        **(output.get("meta") if isinstance(output.get("meta"), dict) else {}),
        "schema_normalizer": "applied",
        "status": "success" if not errors else "validation_error",
    }
    return {
        "typed_quiz_output": output,
        "progress_quiz_output": output,
        "quiz_schema_validation_result": {
            "status": "success" if not errors else "normalized_with_warnings",
            "question_count": len(normalized),
            "errors": errors,
        },
    }


@log_node_runtime("quiz_balance_review_node")
def quiz_balance_review_node(state: OverallState) -> Command[str]:
    output = dict(state.get("progress_quiz_output")) if isinstance(state.get("progress_quiz_output"), dict) else {}
    questions = output.get("questions") if isinstance(output.get("questions"), list) else []
    blueprint = _quiz_blueprint_from_state(state, len(questions))
    balanced = _balanced_quiz_questions([item for item in questions if isinstance(item, dict)], blueprint)
    output["questions"] = balanced
    counts = _purpose_counts(balanced)
    output["meta"] = {
        **(output.get("meta") if isinstance(output.get("meta"), dict) else {}),
        "balance_review": "applied",
    }
    target = "progress_quiz_storage_node" if state.get("pipeline_type") == "progress" else "quiz_material_adapter_node"
    return Command(
        update={
        "progress_quiz_output": output,
        "balanced_quiz_questions": balanced,
        "quiz_balance_review_result": {
            "status": "success" if balanced else "empty",
            "question_count": len(balanced),
            "purpose_counts": counts,
            "target_counts": blueprint.get("target_counts") or {},
            "target_ratios": blueprint.get("target_ratios") or {},
        },
        },
        goto=target,
    )


@log_node_runtime("quiz_material_adapter_node")
def quiz_material_adapter_node(state: OverallState) -> OverallState:
    output = state.get("progress_quiz_output") if isinstance(state.get("progress_quiz_output"), dict) else {}
    meta = output.get("meta") if isinstance(output.get("meta"), dict) else {}
    questions = output.get("questions") if isinstance(output.get("questions"), list) else []
    quiz_material = {
        "meta": {
            "content_type": "quiz",
            "status": str(meta.get("status") or "success"),
            "source": str(meta.get("source") or "quiz_typed_generation_node"),
            "source_mode": str(meta.get("source_mode") or state.get("quiz_source_mode") or "generated"),
        },
        "title": str(output.get("title") or _title_for(state, "quiz")),
        "summary": str(output.get("summary") or "根据测验蓝图生成的多题型测试题。"),
        "payload": {"questions": [item for item in questions if isinstance(item, dict)]},
        "evidence_refs": _quiz_evidence_refs(state),
        "safety_notes": [],
        "next_actions": [],
    }
    return {
        "generated_materials": {"quiz": quiz_material},
        "final_materials": {"quiz": quiz_material},
        "generated_content": quiz_material,
        "generated_question_content": quiz_material,
        "final_question_output": quiz_material,
        "final_output": quiz_material,
    }


@log_node_runtime("course_resource_quiz_selection_node")
def course_resource_quiz_selection_node(state: OverallState) -> OverallState:
    quiz_bank = _question_bank_from_state(state)
    policy = state.get("quiz_difficulty_policy") if isinstance(state.get("quiz_difficulty_policy"), dict) else {}
    question_count = _question_count_for_selection(state, len(quiz_bank))
    selected = _select_course_resource_questions(quiz_bank, policy, question_count, state)
    output = {
        "meta": {
            "content_type": "quiz",
            "status": "success" if selected else "empty",
            "source": "course_resource_quiz_selection_node",
            "source_mode": "course_resource_selection",
        },
        "title": _title_for(state, "quiz"),
        "summary": "根据用户量化学习数据从课程题库中选择的测试题。",
        "questions": selected,
    }
    difficulty = _resource_difficulty_for_state(
        state,
        "quiz",
        f"{state.get('request_id') or state.get('chapter_id') or 'chapter'}:course_resource_quiz",
        source_node="course_resource_quiz_selection_node",
        resource_meta={
            "title": str(output.get("title") or _title_for(state, "quiz")),
            "summary": str(output.get("summary") or ""),
            "question_count": len(selected),
            "selection_source": "course_resources",
        },
    )
    _record_resource_difficulty(state, difficulty)
    output["meta"]["resource_difficulty"] = difficulty["resource_difficulty"]
    output["meta"]["profile_score"] = difficulty["profile_score"]
    return {
        "quiz_bank": quiz_bank,
        "quiz_selection_policy": {
            **policy,
            "question_count": question_count,
            "source": "course_resources",
        },
        "selected_quiz_questions": selected,
        "quiz_selection_result": {
            "status": "success" if selected else "empty",
            "source": "course_resources",
            "available_count": len(quiz_bank),
            "selected_count": len(selected),
            "selected_question_ids": [str(item.get("question_id") or item.get("id") or "") for item in selected],
            "target_difficulty": str(policy.get("target_difficulty") or ""),
            "resource_difficulty": difficulty["resource_difficulty"],
        },
        "progress_quiz_output": output,
        "progress_quiz_generation_raw_output": "",
        "resource_difficulty_records": {"quiz": difficulty},
    }


@log_node_runtime("course_resource_quiz_persistence_node")
def course_resource_quiz_persistence_node(state: OverallState) -> OverallState:
    output = state.get("progress_quiz_output") if isinstance(state.get("progress_quiz_output"), dict) else {}
    questions = output.get("questions") if isinstance(output.get("questions"), list) else []
    selected = [item for item in questions if isinstance(item, dict)]
    saved = save_question_set_json(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or ""),
        title=str(output.get("title") or _title_for(state, "quiz")),
        questions=selected,
        metadata={
            "course_id": str(state.get("course_id") or ""),
            "chapter_id": str(state.get("chapter_id") or ""),
            "content_type": "quiz",
            "question_scope": "path_generated",
            "source": "course_resource_quiz_selection_node",
            "source_mode": "course_resource_selection",
        },
        storage_root=state.get("_storage_root"),
    )
    return {
        "saved_outputs": {"quiz": saved},
        "question_artifact_id": str(saved.get("artifact_id") or ""),
        "question_artifact_paths": {"questions": str(saved.get("questions_path") or "")},
        "saved_question_artifact": saved,
        "artifact_id": str(saved.get("artifact_id") or ""),
        "artifact_paths": {"questions": str(saved.get("questions_path") or "")},
        "saved_artifact": saved,
        "course_resource_quiz_persistence_result": {
            "status": "success" if selected else "empty",
            "source": "course_resource_quiz_persistence_node",
            "selected_count": len(selected),
            "artifact_id": str(saved.get("artifact_id") or ""),
            "questions_path": str(saved.get("questions_path") or ""),
        },
    }


@log_node_runtime("progress_quiz_storage_node")
def progress_quiz_storage_node(state: OverallState) -> OverallState:
    output = state.get("progress_quiz_output") if isinstance(state.get("progress_quiz_output"), dict) else {}
    meta = output.get("meta") if isinstance(output.get("meta"), dict) else {}
    questions = output.get("questions") if isinstance(output.get("questions"), list) else []
    quiz_material = {
        "meta": {
            "content_type": "quiz",
            "status": str(meta.get("status") or "success"),
            "source": str(meta.get("source") or "progress_quiz_generation_node"),
            "source_mode": str(meta.get("source_mode") or state.get("quiz_source_mode") or "generated"),
        },
        "title": str(output.get("title") or _title_for(state, "quiz")),
        "summary": str(output.get("summary") or "根据章节重点生成的测试题。"),
        "payload": {"questions": [item for item in questions if isinstance(item, dict)]},
        "evidence_refs": [],
        "safety_notes": [],
        "next_actions": [],
    }
    materials = dict(state.get("progress_patch_materials")) if isinstance(state.get("progress_patch_materials"), dict) else {}
    materials["quiz"] = quiz_material
    return {
        "progress_patch_materials": materials,
        "generated_materials": materials,
        "final_materials": materials,
        "generated_question_content": quiz_material,
        "final_question_output": quiz_material,
        "personalization_locked_material_types": ["quiz"],
    }


def build_progress_personalization_update(state: OverallState) -> OverallState:
    raw = _invoke_progress_llm(state, _progress_personalization_prompt(state))
    data = _load_json_object(raw)
    final_materials = _merge_progress_personalized_materials(state, data)
    quiz_output = state.get("progress_quiz_output") if isinstance(state.get("progress_quiz_output"), dict) else {}
    if quiz_output:
        final_materials["quiz"] = {
            "meta": {"content_type": "quiz", "status": "success", "source": "progress_quiz_storage_node"},
            "title": str(quiz_output.get("title") or _title_for(state, "quiz")),
            "summary": str(quiz_output.get("summary") or "根据章节重点生成的测试题。"),
            "payload": {"questions": quiz_output.get("questions") if isinstance(quiz_output.get("questions"), list) else []},
            "evidence_refs": [],
            "safety_notes": [],
            "next_actions": [],
        }
    update: OverallState = {
        "progress_personalized_materials": final_materials,
        "progress_personalization_raw_output": raw,
        "final_materials": final_materials,
        "personalized_output": {
            "meta": {"status": "success", "pipeline_type": "progress"},
            "learning_stage": state.get("learning_stage") or {},
            "materials": final_materials,
        },
        "final_output": {},
    }
    if isinstance(final_materials.get("lecture"), dict):
        update.update(
            {
                "progress_personalized_lecture_output": final_materials["lecture"],
                "personalized_lecture_output": final_materials["lecture"],
            }
        )
    if isinstance(final_materials.get("practice"), dict):
        update.update(
            {
                "progress_personalized_practice_output": final_materials["practice"],
                "personalized_practice_guide_output": final_materials["practice"],
            }
        )
    if isinstance(final_materials.get("quiz"), dict):
        update["personalized_question_output"] = final_materials["quiz"]
    return update


def _invoke_progress_llm(state: OverallState, prompt: str) -> str:
    model = state.get("_progress_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([_human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _progress_model
    if _progress_model is None:
        from langchain_deepseek import ChatDeepSeek

        _progress_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _progress_model


def _retrieve_package(state: OverallState, questions: list[Any]) -> RagPackage:
    retriever = state.get("_rag_retriever") or SimpleResourceRetriever()
    package = retriever.retrieve([str(item) for item in questions if str(item).strip()])
    return package if isinstance(package, RagPackage) else RagPackage.model_validate(package)


def _gap_focus_prompt(state: OverallState) -> str:
    return f"""
progress task: gap_focus_analysis
Return JSON only with related_knowledge_gaps, patch_target_points, quiz_relevant_focus_points.
Match learner knowledge gaps to chapter focus. Do not invent facts.

chapter_focus:
{json.dumps(state.get("chapter_focus") or {}, ensure_ascii=False)}

knowledge_gap_documents:
{json.dumps(state.get("knowledge_gap_documents") or {}, ensure_ascii=False)}

learning_progress:
{json.dumps(state.get("learning_progress") or {}, ensure_ascii=False)}
""".strip()


def _rag_planner_prompt(state: OverallState) -> str:
    return f"""
progress task: progress_rag_planner
Return JSON only.
Generate two separated query lists:
- progress_patch_rag_queries: based on knowledge gaps + chapter focus.
- progress_quiz_rag_queries: based only on chapter focus.

chapter_focus:
{json.dumps(state.get("chapter_focus") or {}, ensure_ascii=False)}

gap_focus_analysis:
{json.dumps(state.get("gap_focus_analysis") or {}, ensure_ascii=False)}
""".strip()


def _patch_generation_prompt(state: OverallState) -> str:
    return f"""
progress task: progress_patch_generation
Return JSON only with lecture_patches and practice_patches.
Generate short patches only. Each patch should be concise, normally 120-250 Chinese characters.
Do not rewrite the full chapter. Do not add facts not supported by base material or RAG evidence.
Keep patch_id, target_section, related_gap_ids, reason, content, evidence_refs.
All learner-facing text in target_section, reason, and content must be Chinese, except necessary
technical abbreviations such as CNC, G code, and M code. Never place retrieval file names,
file paths, patch IDs, evidence IDs, or RAG metadata inside content.

chapter_focus:
{json.dumps(state.get("chapter_focus") or {}, ensure_ascii=False)}

patch_rag_package:
{json.dumps(state.get("patch_rag_package") or {}, ensure_ascii=False)}

base_materials:
{json.dumps(state.get("chapter_base_materials") or {}, ensure_ascii=False)}
""".strip()


def _quiz_generation_prompt(state: OverallState) -> str:
    return f"""
progress task: progress_quiz_generation
Return JSON only with title, summary, questions.
Generate quiz from chapter focus, quiz RAG, patch RAG, reference examples, difficulty policy,
and quiz_generation_blueprint. Chapter-core questions must mainly use quiz_rag_package.
Gap-remediation questions must use patch_rag_package and related_knowledge_gaps. Follow
the target_counts in quiz_generation_blueprint as closely as possible.
Do not personalize language here. Include knowledge_points, core_exam_points,
question_purpose, and related_gap_ids for every question.
All learner-facing text, including title, summary, stems, options, explanations, knowledge-point
names, and core exam points, must be Chinese except necessary technical abbreviations.

chapter_focus:
{json.dumps(state.get("chapter_focus") or {}, ensure_ascii=False)}

quiz_generation_blueprint:
{json.dumps(state.get("quiz_generation_blueprint") or {}, ensure_ascii=False)}

related_knowledge_gaps:
{json.dumps(state.get("related_knowledge_gaps") or [], ensure_ascii=False)}

reference_quiz:
{json.dumps(state.get("reference_quiz") or {}, ensure_ascii=False)}

quiz_rag_package:
{json.dumps(state.get("quiz_rag_package") or {}, ensure_ascii=False)}

patch_rag_package:
{json.dumps(state.get("patch_rag_package") or {}, ensure_ascii=False)}

quiz_difficulty_policy:
{json.dumps(state.get("quiz_difficulty_policy") or {}, ensure_ascii=False)}
""".strip()


def _typed_quiz_generation_prompt(state: OverallState) -> str:
    return f"""
progress task: typed_quiz_generation
Return JSON only with title, summary, questions.
Generate a multi-type quiz strictly following quiz_generation_blueprint.slots.
Return questions in the exact same order as slots.
Do not change sequence, question_type, question_purpose, difficulty, points, or capability_dimension.

Question type rules:
- single_choice: options must contain 4 choices; answer must be A/B/C/D.
- true_false: options must be ["正确", "错误"]; answer must be A for 正确 or B for 错误.
- cloze: options must be []; answer and reference_answer are required.
- short_answer: options must be []; reference_answer and scoring_rubric.key_points are required.

All questions must include knowledge_points, core_exam_points, concise_explanation,
detailed_explanation, question_purpose, and related_gap_ids.
Chapter-core questions mainly use quiz_rag_package. Gap-remediation questions use patch_rag_package
and related_knowledge_gaps. Do not personalize language here.
All learner-facing text must be Chinese except necessary technical abbreviations such as CNC,
G code, and M code.

task:
{state.get("task") or state.get("quiz_generation_prompt") or state.get("raw_prompt") or ""}

quiz_generation_blueprint:
{json.dumps(state.get("quiz_generation_blueprint") or {}, ensure_ascii=False)}

chapter_focus:
{json.dumps(state.get("chapter_focus") or {}, ensure_ascii=False)}

related_knowledge_gaps:
{json.dumps(state.get("related_knowledge_gaps") or [], ensure_ascii=False)}

quiz_rag_package:
{json.dumps(state.get("quiz_rag_package") or {}, ensure_ascii=False)}

patch_rag_package:
{json.dumps(state.get("patch_rag_package") or {}, ensure_ascii=False)}

reference_quiz:
{json.dumps(state.get("reference_quiz") or {}, ensure_ascii=False)}
""".strip()


def _progress_personalization_prompt(state: OverallState) -> str:
    patch_materials = _student_facing_patch_materials(state.get("progress_patch_materials"))
    base_materials = _student_facing_base_materials(state.get("chapter_base_materials"))
    return f"""
progress task: progress_personalization
Return JSON only. Personalize non-quiz materials only.
Combine base chapter material and visible patches, but do not fully hide patch structure.
Use profile.md only to adjust language, order, and guidance. Do not add new facts.
Rewrite base_content as student-facing chapter material while preserving its supported facts.
All learner-facing text must be Chinese except necessary technical abbreviations such as CNC,
G code, and M code.
Remove authoring notes and implementation-facing text, including references to prompts, nodes,
files, generators, artificial reference drafts, or personalization instructions.
Do not expose internal workflow descriptions to the learner.
Do not place patch IDs, reason fields, evidence IDs, retrieval file names, absolute paths, or
system paths inside base_content, knowledge-gap patch content, summaries, or learning guidance.
必须保留原讲义中已有的 Markdown 图片相对引用，例如 ![说明](assets/xxx.png)。
Expected top-level keys may include lecture and practice. Each material must contain title,
summary, base_content, knowledge_gap_patches, and learning_guidance.

profile_md:
{state.get("profile_md_content") or ""}

learning_progress:
{json.dumps(state.get("learning_progress") or {}, ensure_ascii=False)}

progress_patch_materials:
{json.dumps(patch_materials, ensure_ascii=False)}

base_materials:
{json.dumps(base_materials, ensure_ascii=False)}
""".strip()


def _fallback_gap_focus_analysis(state: OverallState) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    gaps = ((state.get("knowledge_gap_documents") or {}).get("json") or {}).get("gaps") or []
    focus_items = (state.get("chapter_focus") or {}).get("focus_items") or []
    first_gap = gaps[0] if gaps and isinstance(gaps[0], dict) else {}
    lecture_focus = _first_focus(focus_items, "lecture")
    quiz_focus = _first_focus(focus_items, "quiz")
    related = [
        {
            "gap_id": str(first_gap.get("gap_id") or "gap_auto"),
            "concept": str(first_gap.get("concept") or "章节知识点"),
            "matched_focus_ids": [str(lecture_focus.get("id") or "")],
            "priority": str(first_gap.get("severity") or "medium"),
            "reason": "根据当前未掌握知识点与章节重点建立关联。",
        }
    ]
    patch_targets = [
        {
            "target_id": "patch_auto",
            "material_type": "lecture",
            "focus_id": str(lecture_focus.get("id") or ""),
            "gap_ids": [related[0]["gap_id"]],
            "query_hint": " ".join(_focus_keywords(lecture_focus)),
        }
    ]
    quiz_points = [{"focus_id": str(quiz_focus.get("id") or ""), "query_hint": " ".join(_focus_keywords(quiz_focus))}]
    return related, patch_targets, quiz_points


def _fallback_patch_queries(state: OverallState) -> list[str]:
    queries = []
    for item in state.get("patch_target_points") or []:
        if isinstance(item, dict) and str(item.get("query_hint") or "").strip():
            queries.append(str(item["query_hint"]).strip())
    return queries or _focus_queries(state, category="lecture") or _focus_queries(state)


def _focus_queries(state: OverallState, *, category: str | None = None) -> list[str]:
    focus_items = (state.get("chapter_focus") or {}).get("focus_items") or []
    queries: list[str] = []
    for item in focus_items:
        if not isinstance(item, dict):
            continue
        if category and str(item.get("category") or "") != category:
            continue
        queries.extend(_focus_keywords(item))
    return queries


def _fallback_lecture_patches(state: OverallState) -> list[dict[str, Any]]:
    evidence = (state.get("patch_rag_package") or {}).get("evidence") or []
    text = str(evidence[0].get("text") or "") if evidence and isinstance(evidence[0], dict) else ""
    return [
        {
            "patch_id": "patch_auto",
            "target_section": (state.get("chapter_focus") or {}).get("summary") or "章节重点",
            "related_gap_ids": [item.get("gap_id") for item in state.get("related_knowledge_gaps") or [] if isinstance(item, dict)],
            "reason": "根据相关知识漏洞和检索依据生成补充内容。",
            "content": text[:300] or "请结合章节基础讲义复习这一知识重点。",
            "evidence_refs": ["patch_rag:0"] if text else [],
        }
    ]


def _fallback_quiz_questions(state: OverallState) -> list[dict[str, Any]]:
    focus = (state.get("chapter_focus") or {}).get("summary") or "章节重点"
    return [
        {
            "stem": f"下列哪项表述最符合“{focus}”？",
            "options": ["符合章节重点的表述", "与本章无关的操作", "未经验证的说法", "以上均不正确"],
            "answer": "A",
            "explanation": "本题根据章节重点和已有依据生成。",
            "difficulty": (state.get("quiz_difficulty_policy") or {}).get("target_difficulty") or "easy",
            "knowledge_points": [
                {
                    "id": f"{state.get('course_id')}.{state.get('chapter_id')}.focus",
                    "name": str(focus),
                    "chapter_id": str(state.get("chapter_id") or ""),
                    "weight": 1.0,
                }
            ],
            "core_exam_points": [str(focus)],
        }
    ]


def _fallback_typed_quiz_questions(state: OverallState) -> list[dict[str, Any]]:
    slots = _quiz_slots_from_state(state)
    if not slots:
        slots = _quiz_blueprint_slots(
            question_count=4,
            type_counts={"single_choice": 1, "true_false": 1, "cloze": 1, "short_answer": 1},
            purpose_counts={"chapter_core": 3, "gap_remediation": 1},
            difficulty_policy={},
            related_gap_ids=_related_gap_ids(state),
        )
    focus = str((state.get("chapter_focus") or {}).get("summary") or state.get("task") or "章节重点")
    questions = []
    for slot in slots:
        question_type = str(slot.get("question_type") or "single_choice")
        base = {
            "sequence": _int_or_default(slot.get("sequence"), len(questions) + 1),
            "stem": f"请围绕“{focus}”完成本题。",
            "question_type": question_type,
            "answer": "A" if question_type in {"single_choice", "true_false"} else focus,
            "reference_answer": "正确" if question_type == "true_false" else focus,
            "explanation": "本题根据章节重点和检索证据生成。",
            "concise_explanation": "依据章节重点作答。",
            "detailed_explanation": "本题答案应以章节重点和检索证据为依据。",
            "difficulty": str(slot.get("difficulty") or "easy"),
            "points": slot.get("points"),
            "capability_dimension": str(slot.get("capability_dimension") or "foundations"),
            "question_purpose": str(slot.get("question_purpose") or "chapter_core"),
            "related_gap_ids": slot.get("related_gap_ids") if isinstance(slot.get("related_gap_ids"), list) else [],
            "knowledge_points": [
                {
                    "id": _knowledge_point_id(focus, state, 1),
                    "name": focus,
                    "chapter_id": str(state.get("chapter_id") or ""),
                    "weight": 1.0,
                }
            ],
            "core_exam_points": [focus],
        }
        if question_type == "single_choice":
            base["options"] = ["符合章节重点的表述", "与本章无关的操作", "未经验证的说法", "以上均不正确"]
        elif question_type == "true_false":
            base["stem"] = f"{focus}是本章节需要掌握的内容。"
            base["options"] = ["正确", "错误"]
            base["reference_answer"] = "正确"
        elif question_type == "short_answer":
            base["options"] = []
            base["scoring_rubric"] = {
                "key_points": [
                    {"description": "回答应覆盖章节核心概念。", "points": base.get("points") or 7}
                ]
            }
        else:
            base["options"] = []
        questions.append(base)
    return questions


def _quiz_blueprint_ratio_policy(state: OverallState) -> dict[str, float]:
    policy = _chapter_quiz_policy(state)
    configured_gap_ratio = _optional_ratio(policy.get("gap_remediation_ratio") or policy.get("gap_ratio"))
    configured_core_ratio = _optional_ratio(policy.get("chapter_core_ratio") or policy.get("core_ratio"))
    if configured_gap_ratio is not None:
        gap_ratio = configured_gap_ratio
    else:
        profile = state.get("user_quantitative_profile") if isinstance(state.get("user_quantitative_profile"), dict) else {}
        average_score = _coerce_weight(profile.get("average_score"), default=0.65)
        if average_score < 0.45:
            gap_ratio = 0.4
        elif average_score < 0.75:
            gap_ratio = 0.3
        else:
            gap_ratio = 0.2
    if configured_core_ratio is not None:
        core_ratio = configured_core_ratio
        gap_ratio = min(gap_ratio, 1.0 - core_ratio)
    else:
        core_ratio = 1.0 - gap_ratio
    core_ratio = round(min(max(core_ratio, 0.0), 1.0), 2)
    gap_ratio = round(min(max(1.0 - core_ratio, 0.0), 1.0), 2)
    return {"chapter_core": core_ratio, "gap_remediation": gap_ratio}


def _user_quiz_blueprint_input(state: OverallState) -> dict[str, Any]:
    value = state.get("quiz_blueprint_input")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _parse_regular_quiz_blueprint(state: OverallState, user_blueprint: dict[str, Any]) -> dict[str, Any]:
    has_user_blueprint = bool(user_blueprint)
    question_count = _question_count_from_blueprint(state, user_blueprint)
    related_gap_ids = _clean_string_list(user_blueprint.get("related_gap_ids")) or _related_gap_ids(state)
    target_counts = _purpose_counts_from_blueprint(state, user_blueprint, question_count, has_user_blueprint)
    slots = _slots_from_user_blueprint(state, user_blueprint, question_count, target_counts, related_gap_ids)
    type_counts = _count_slots_by_key(slots, "question_type", QUIZ_TYPE_ORDER)
    difficulty_counts = _count_slots_by_key(slots, "difficulty", ["easy", "normal", "hard"])
    type_policy = _ratio_policy_from_counts(type_counts, question_count)
    blueprint = {
        "status": "success",
        "source": "quiz_blueprint_parser_node",
        "question_count": question_count,
        "target_ratios": _ratio_policy_from_counts(target_counts, question_count),
        "target_counts": target_counts,
        "type_policy": type_policy,
        "type_counts": type_counts,
        "difficulty_counts": difficulty_counts,
        "slots": slots,
        "related_gap_ids": related_gap_ids,
        "source_packages": {
            "chapter_core": {
                "rag_package_key": "quiz_rag_package",
                "evidence_count": _evidence_count(state.get("quiz_rag_package")),
            },
            "gap_remediation": {
                "rag_package_key": "patch_rag_package",
                "evidence_count": _evidence_count(state.get("patch_rag_package")),
            },
        },
        "required_question_fields": [
            "question_purpose",
            "knowledge_points",
            "core_exam_points",
            "related_gap_ids",
            "question_type",
            "reference_answer",
            "points",
            "capability_dimension",
        ],
        "chapter_focus_summary": str((state.get("chapter_focus") or {}).get("summary") or ""),
        "core_exam_points": _clean_string_list(user_blueprint.get("core_exam_points")),
        "knowledge_points": user_blueprint.get("knowledge_points") if isinstance(user_blueprint.get("knowledge_points"), list) else [],
    }
    parse_result = {
        "status": "success",
        "source": "quiz_blueprint_parser_node",
        "input_source": "user_blueprint" if has_user_blueprint else "default",
        "question_count": question_count,
        "target_counts": target_counts,
        "type_counts": type_counts,
        "difficulty_counts": difficulty_counts,
        "slot_count": len(slots),
    }
    return {
        "blueprint": blueprint,
        "slots": slots,
        "type_policy": type_policy,
        "parse_result": parse_result,
    }


def _question_count_from_blueprint(state: OverallState, blueprint: dict[str, Any]) -> int:
    slots = blueprint.get("slots")
    if isinstance(slots, list) and slots:
        return min(max(len([item for item in slots if isinstance(item, dict)]), 1), 50)
    for key in ("question_count", "count", "total"):
        if blueprint.get(key) is not None:
            try:
                return min(max(int(blueprint[key]), 1), 50)
            except (TypeError, ValueError):
                pass
    type_counts = _raw_count_total(blueprint.get("type_counts"))
    if type_counts > 0:
        return min(type_counts, 50)
    return _question_count_for_generation(state)


def _purpose_counts_from_blueprint(
    state: OverallState,
    blueprint: dict[str, Any],
    question_count: int,
    has_user_blueprint: bool,
) -> dict[str, int]:
    counts = _counts_from_mapping(
        blueprint.get("target_counts") or blueprint.get("purpose_counts") or blueprint.get("question_purpose_counts"),
        ["chapter_core", "gap_remediation"],
    )
    if not counts:
        if has_user_blueprint:
            return {"chapter_core": question_count, "gap_remediation": 0}
        return _target_counts_for_ratio(question_count, _quiz_blueprint_ratio_policy(state))
    return _fit_counts_to_total(counts, question_count, ["chapter_core", "gap_remediation"], fill_key="chapter_core")


def _slots_from_user_blueprint(
    state: OverallState,
    blueprint: dict[str, Any],
    question_count: int,
    purpose_counts: dict[str, int],
    related_gap_ids: list[str],
) -> list[dict[str, Any]]:
    raw_slots = blueprint.get("slots")
    if isinstance(raw_slots, list) and raw_slots:
        return _normalize_blueprint_slots(raw_slots, state, question_count, related_gap_ids)
    type_counts = _type_counts_from_blueprint(blueprint, question_count)
    difficulty_sequence = _difficulty_sequence_from_blueprint(blueprint, question_count)
    purposes = _purpose_sequence(question_count, purpose_counts)
    types = _sequence_from_counts(type_counts, QUIZ_TYPE_ORDER, question_count)
    slots = []
    for index in range(question_count):
        question_type = types[index] if index < len(types) else "single_choice"
        difficulty = difficulty_sequence[index] if index < len(difficulty_sequence) else "easy"
        purpose = purposes[index] if index < len(purposes) else "chapter_core"
        slots.append(
            {
                "sequence": index + 1,
                "question_type": question_type,
                "question_purpose": purpose,
                "difficulty": difficulty,
                "points": _points_for(question_type, difficulty),
                "capability_dimension": QUIZ_CAPABILITY_DIMENSIONS[index % len(QUIZ_CAPABILITY_DIMENSIONS)],
                "related_gap_ids": related_gap_ids if purpose == "gap_remediation" else [],
            }
        )
    return slots


def _normalize_blueprint_slots(
    raw_slots: list[Any],
    state: OverallState,
    question_count: int,
    related_gap_ids: list[str],
) -> list[dict[str, Any]]:
    slots = []
    for index, raw_slot in enumerate(raw_slots, start=1):
        if not isinstance(raw_slot, dict):
            continue
        question_type = _clean_question_type(raw_slot.get("question_type") or raw_slot.get("type"))
        difficulty = _difficulty_key(raw_slot.get("difficulty"))
        purpose = str(raw_slot.get("question_purpose") or raw_slot.get("purpose") or "chapter_core")
        if purpose not in {"chapter_core", "gap_remediation"}:
            purpose = "chapter_core"
        slot_gap_ids = _clean_string_list(raw_slot.get("related_gap_ids")) or (related_gap_ids if purpose == "gap_remediation" else [])
        slots.append(
            {
                "sequence": _int_or_default(raw_slot.get("sequence"), len(slots) + 1),
                "question_type": question_type,
                "question_purpose": purpose,
                "difficulty": difficulty,
                "points": _coerce_points(raw_slot.get("points"), question_type, difficulty),
                "capability_dimension": str(raw_slot.get("capability_dimension") or "").strip()
                or QUIZ_CAPABILITY_DIMENSIONS[(index - 1) % len(QUIZ_CAPABILITY_DIMENSIONS)],
                "related_gap_ids": slot_gap_ids,
            }
        )
        if len(slots) >= question_count:
            break
    if len(slots) < question_count:
        fallback = _quiz_blueprint_slots(
            question_count=question_count - len(slots),
            type_counts=_quiz_type_counts(question_count - len(slots)),
            purpose_counts={"chapter_core": question_count - len(slots), "gap_remediation": 0},
            difficulty_policy={},
            related_gap_ids=related_gap_ids,
        )
        for slot in fallback:
            item = dict(slot)
            item["sequence"] = len(slots) + 1
            slots.append(item)
    return slots


def _type_counts_from_blueprint(blueprint: dict[str, Any], question_count: int) -> dict[str, int]:
    counts = _counts_from_mapping(blueprint.get("type_counts"), QUIZ_TYPE_ORDER)
    if not counts and isinstance(blueprint.get("type_ratios"), dict):
        counts = _allocate_counts(question_count, blueprint["type_ratios"], QUIZ_TYPE_ORDER)
    if not counts:
        counts = _quiz_type_counts(question_count)
    return _fit_counts_to_total(counts, question_count, QUIZ_TYPE_ORDER, fill_key="single_choice")


def _difficulty_sequence_from_blueprint(blueprint: dict[str, Any], question_count: int) -> list[str]:
    counts = _counts_from_mapping(blueprint.get("difficulty_counts"), ["easy", "normal", "hard"])
    if counts:
        return _fit_sequence_to_total(_sequence_from_counts(counts, list(counts), question_count), question_count, "easy")
    ratios = blueprint.get("difficulty_ratios")
    if isinstance(ratios, dict):
        counts = _allocate_counts(question_count, ratios, ["easy", "normal", "hard"])
        return _sequence_from_counts(counts, ["easy", "normal", "hard"], question_count)
    return _difficulty_sequence(question_count, {})


def _counts_from_mapping(value: Any, allowed: list[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    allowed_set = set(allowed)
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        normalized = _clean_question_type(key) if allowed == QUIZ_TYPE_ORDER else str(key or "").strip()
        if normalized not in allowed_set:
            continue
        count = _int_or_default(raw_count, 0)
        if count > 0:
            counts[normalized] = counts.get(normalized, 0) + count
        elif normalized not in counts:
            counts[normalized] = 0
    return counts


def _raw_count_total(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(max(_int_or_default(item, 0), 0) for item in value.values())


def _fit_counts_to_total(counts: dict[str, int], total: int, order: list[str], *, fill_key: str) -> dict[str, int]:
    result = {key: max(_int_or_default(counts.get(key), 0), 0) for key in order}
    assigned = sum(result.values())
    if assigned < total:
        result[fill_key] = result.get(fill_key, 0) + (total - assigned)
    elif assigned > total:
        overflow = assigned - total
        for key in reversed(order):
            take = min(result.get(key, 0), overflow)
            result[key] -= take
            overflow -= take
            if overflow <= 0:
                break
    return result


def _sequence_from_counts(counts: dict[str, int], order: list[str], total: int) -> list[str]:
    sequence = []
    seen = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        sequence.extend([key] * max(_int_or_default(counts.get(key), 0), 0))
    return _fit_sequence_to_total(sequence, total, order[0] if order else "single_choice")


def _fit_sequence_to_total(sequence: list[str], total: int, fill_value: str) -> list[str]:
    if len(sequence) < total:
        sequence = [*sequence, *([fill_value] * (total - len(sequence)))]
    return sequence[:total]


def _count_slots_by_key(slots: list[dict[str, Any]], key: str, order: list[str]) -> dict[str, int]:
    counts = {item: 0 for item in order}
    for slot in slots:
        value = str(slot.get(key) or "").strip()
        if value in counts:
            counts[value] += 1
    return counts


def _ratio_policy_from_counts(counts: dict[str, int], total: int) -> dict[str, float]:
    denominator = max(total, 1)
    return {key: round(max(value, 0) / denominator, 2) for key, value in counts.items()}


def _question_count_for_generation(state: OverallState) -> int:
    policy = _chapter_quiz_policy(state)
    raw_count = state.get("quiz_question_count") or policy.get("question_count") or policy.get("count")
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        count = 10
    return min(max(count, 1), 50)


def _quiz_type_counts(question_count: int) -> dict[str, int]:
    if question_count >= len(QUIZ_TYPE_ORDER):
        counts = {key: 1 for key in QUIZ_TYPE_ORDER}
        remaining = question_count - len(QUIZ_TYPE_ORDER)
        extra = _allocate_counts(remaining, QUIZ_TYPE_POLICY, QUIZ_TYPE_ORDER) if remaining else {}
        for key, value in extra.items():
            counts[key] += value
        return counts
    return _allocate_counts(question_count, QUIZ_TYPE_POLICY, QUIZ_TYPE_ORDER)


def _allocate_counts(total: int, ratios: dict[str, float], order: list[str]) -> dict[str, int]:
    counts = {key: int(total * _coerce_weight(ratios.get(key), default=0.0)) for key in order}
    assigned = sum(counts.values())
    remainders = sorted(
        ((total * _coerce_weight(ratios.get(key), default=0.0) - counts[key], index, key) for index, key in enumerate(order)),
        key=lambda item: (-item[0], item[1]),
    )
    cursor = 0
    while assigned < total and remainders:
        key = remainders[cursor % len(remainders)][2]
        counts[key] += 1
        assigned += 1
        cursor += 1
    return counts


def _quiz_blueprint_slots(
    *,
    question_count: int,
    type_counts: dict[str, int],
    purpose_counts: dict[str, int],
    difficulty_policy: dict[str, Any],
    related_gap_ids: list[str],
) -> list[dict[str, Any]]:
    types = [question_type for question_type in QUIZ_TYPE_ORDER for _ in range(max(int(type_counts.get(question_type) or 0), 0))]
    purposes = _purpose_sequence(question_count, purpose_counts)
    difficulties = _difficulty_sequence(question_count, difficulty_policy)
    slots = []
    for index in range(question_count):
        question_type = types[index] if index < len(types) else "single_choice"
        purpose = purposes[index] if index < len(purposes) else "chapter_core"
        difficulty = difficulties[index] if index < len(difficulties) else "easy"
        slots.append(
            {
                "sequence": index + 1,
                "question_type": question_type,
                "question_purpose": purpose,
                "difficulty": difficulty,
                "points": _points_for(question_type, difficulty),
                "capability_dimension": QUIZ_CAPABILITY_DIMENSIONS[index % len(QUIZ_CAPABILITY_DIMENSIONS)],
                "related_gap_ids": related_gap_ids if purpose == "gap_remediation" else [],
            }
        )
    return slots


def _purpose_sequence(question_count: int, purpose_counts: dict[str, int]) -> list[str]:
    gap_count = max(_int_or_default(purpose_counts.get("gap_remediation"), 0), 0)
    core_count = max(question_count - gap_count, 0)
    result = []
    remaining_core = core_count
    remaining_gap = gap_count
    for index in range(question_count):
        if index > 0 and remaining_gap > 0 and (index % 2 == 1 or remaining_core <= 0):
            result.append("gap_remediation")
            remaining_gap -= 1
        elif remaining_core > 0:
            result.append("chapter_core")
            remaining_core -= 1
        elif remaining_gap > 0:
            result.append("gap_remediation")
            remaining_gap -= 1
    return result


def _difficulty_sequence(question_count: int, policy: dict[str, Any]) -> list[str]:
    ratios = {
        "easy": _coerce_weight(policy.get("easy_ratio"), default=0.3),
        "normal": _coerce_weight(policy.get("normal_ratio"), default=0.5),
        "hard": _coerce_weight(policy.get("hard_ratio"), default=0.2),
    }
    counts = _allocate_counts(question_count, ratios, ["easy", "normal", "hard"])
    return [difficulty for difficulty in ("easy", "normal", "hard") for _ in range(counts.get(difficulty, 0))]


def _points_for(question_type: str, difficulty: str) -> float:
    if question_type in {"single_choice", "true_false"}:
        return 2.0 if difficulty == "hard" else 1.5 if difficulty == "normal" else 1.0
    return 12.0 if difficulty == "hard" else 10.0 if difficulty == "normal" else 7.0


def _target_counts_for_ratio(question_count: int, ratios: dict[str, float]) -> dict[str, int]:
    gap_count = int(round(question_count * _coerce_weight(ratios.get("gap_remediation"), default=0.3)))
    if question_count > 1 and gap_count <= 0:
        gap_count = 1
    if gap_count >= question_count and question_count > 1:
        gap_count = question_count - 1
    core_count = max(question_count - gap_count, 0)
    return {"chapter_core": core_count, "gap_remediation": gap_count}


def _optional_ratio(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(parsed, 0.0), 1.0)


def _related_gap_ids(state: OverallState) -> list[str]:
    gap_ids = []
    for gap in state.get("related_knowledge_gaps") or []:
        if not isinstance(gap, dict):
            continue
        gap_id = str(gap.get("gap_id") or "").strip()
        if gap_id and gap_id not in gap_ids:
            gap_ids.append(gap_id)
    return gap_ids


def _evidence_count(value: Any) -> int:
    if isinstance(value, dict) and isinstance(value.get("evidence"), list):
        return len(value["evidence"])
    return 0


def _quiz_blueprint_from_state(state: OverallState, question_count: int) -> dict[str, Any]:
    blueprint = state.get("quiz_generation_blueprint") if isinstance(state.get("quiz_generation_blueprint"), dict) else {}
    if blueprint:
        return blueprint
    ratios = _quiz_blueprint_ratio_policy(state)
    count = question_count or _question_count_for_generation(state)
    return {
        "question_count": count,
        "target_ratios": ratios,
        "target_counts": _target_counts_for_ratio(count, ratios),
        "related_gap_ids": _related_gap_ids(state),
    }


def _balanced_quiz_questions(questions: list[dict[str, Any]], blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    if not questions:
        return []
    target_counts = blueprint.get("target_counts") if isinstance(blueprint.get("target_counts"), dict) else {}
    question_count = _int_or_default(blueprint.get("question_count"), len(questions))
    question_count = min(max(question_count, 1), len(questions))
    tagged = [_tag_question_purpose(question, blueprint) for question in questions]
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for purpose in ("chapter_core", "gap_remediation"):
        target = min(_int_or_default(target_counts.get(purpose), 0), question_count - len(selected))
        for question in tagged:
            if len([item for item in selected if item.get("question_purpose") == purpose]) >= target:
                break
            if question.get("question_purpose") != purpose:
                continue
            _append_balanced_question(selected, used, question)
    if len(selected) < question_count:
        for question in tagged:
            if len(selected) >= question_count:
                break
            _append_balanced_question(selected, used, question)
    return sorted(selected[:question_count], key=lambda item: _int_or_default(item.get("sequence"), question_count))


def _tag_question_purpose(question: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    item = dict(question)
    related_gap_ids = _clean_string_list(item.get("related_gap_ids"))
    purpose = str(item.get("question_purpose") or item.get("purpose") or "").strip()
    if purpose not in {"chapter_core", "gap_remediation"}:
        purpose = "gap_remediation" if related_gap_ids else "chapter_core"
    if purpose == "gap_remediation" and not related_gap_ids:
        related_gap_ids = _clean_string_list(blueprint.get("related_gap_ids"))
    item["question_purpose"] = purpose
    item["related_gap_ids"] = related_gap_ids if purpose == "gap_remediation" else related_gap_ids
    return item


def _append_balanced_question(selected: list[dict[str, Any]], used: set[str], question: dict[str, Any]) -> None:
    key = _question_identifier(question)
    if key in used:
        return
    selected.append(dict(question))
    used.add(key)


def _purpose_counts(questions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"chapter_core": 0, "gap_remediation": 0}
    for question in questions:
        purpose = str(question.get("question_purpose") or "chapter_core")
        if purpose not in counts:
            purpose = "chapter_core"
        counts[purpose] += 1
    return counts


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _quiz_strategy_for_state(state: OverallState) -> str:
    policy = _chapter_quiz_policy(state)
    mode = str(policy.get("mode") or "").strip()
    if mode in {"select_from_bank", "select_from_course_resource"}:
        return "select_from_course_resource"
    if mode in {"generate", "generated"}:
        return "generate"
    major = _chapter_major(state.get("chapter_id"))
    return "select_from_course_resource" if major in {4, 5} else "generate"


def _chapter_quiz_policy(state: OverallState) -> dict[str, Any]:
    manifest = state.get("chapter_manifest") if isinstance(state.get("chapter_manifest"), dict) else {}
    policy = manifest.get("quiz_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _chapter_major(chapter_id: Any) -> int | None:
    raw = str(chapter_id or "").split(".", 1)[0]
    try:
        return int(raw)
    except ValueError:
        return None


def _question_bank_from_state(state: OverallState) -> list[dict[str, Any]]:
    bank: list[dict[str, Any]] = []
    seen: set[str] = set()
    reference_quiz = state.get("reference_quiz") if isinstance(state.get("reference_quiz"), dict) else {}
    _extend_question_bank(bank, seen, reference_quiz, source_path=reference_quiz.get("path"), state=state)

    bundle = state.get("course_resource_bundle") if isinstance(state.get("course_resource_bundle"), dict) else {}
    assets = bundle.get("assets") if isinstance(bundle.get("assets"), dict) else {}
    reference_asset = (assets.get("reference_quiz") or {}).get("questions") if isinstance(assets.get("reference_quiz"), dict) else {}
    if isinstance(reference_asset, dict):
        _extend_question_bank(
            bank,
            seen,
            _read_json_file(reference_asset.get("path")),
            source_path=reference_asset.get("path"),
            state=state,
        )

    operation_tasks = assets.get("operation_tasks") if isinstance(assets.get("operation_tasks"), list) else []
    for task in operation_tasks:
        if not isinstance(task, dict):
            continue
        reference = task.get("reference_quiz") if isinstance(task.get("reference_quiz"), dict) else {}
        if not reference:
            continue
        extra = {
            "task_id": str(task.get("task_id") or ""),
            "workpiece_id": str(task.get("workpiece_id") or ""),
        }
        _extend_question_bank(
            bank,
            seen,
            _read_json_file(reference.get("path")),
            source_path=reference.get("path"),
            state=state,
            extra=extra,
        )
    return bank


def _extend_question_bank(
    bank: list[dict[str, Any]],
    seen: set[str],
    payload: dict[str, Any],
    *,
    source_path: Any,
    state: OverallState,
    extra: dict[str, Any] | None = None,
) -> None:
    for question in _questions_from_payload(payload):
        item = dict(question)
        source_question_id = str(item.get("question_id") or item.get("id") or "")
        item.setdefault("question_id", source_question_id or f"course_resource_q_{len(bank) + 1:03d}")
        dedupe_key = str(item.get("question_id") or item.get("stem") or item.get("question_text") or "")
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item.setdefault("source_question_id", source_question_id or str(item["question_id"]))
        item["question_source"] = "course_resources"
        if source_path:
            item["source_path"] = str(source_path)
        if extra:
            item.update({key: value for key, value in extra.items() if value})
        bank.extend(_normalize_progress_questions([item], state))


def _questions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("questions", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _question_count_for_selection(state: OverallState, available_count: int) -> int:
    policy = _chapter_quiz_policy(state)
    raw_count = policy.get("question_count") or policy.get("count")
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        count = min(10, available_count)
    if available_count <= 0:
        return 0
    return min(max(count, 1), available_count)


def _select_course_resource_questions(
    questions: list[dict[str, Any]],
    policy: dict[str, Any],
    question_count: int,
    state: OverallState,
) -> list[dict[str, Any]]:
    if question_count <= 0:
        return []
    groups: dict[str, list[dict[str, Any]]] = {"easy": [], "normal": [], "hard": []}
    for question in questions:
        groups[_difficulty_key(question.get("difficulty"))].append(question)
    priority = _difficulty_priority(policy.get("target_difficulty"))
    quotas = _selection_quotas(groups, policy, question_count, priority)
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for difficulty in priority:
        for question in groups.get(difficulty, [])[: quotas.get(difficulty, 0)]:
            _append_selected_question(selected, used, question, state)
    if len(selected) < question_count:
        for difficulty in priority:
            for question in groups.get(difficulty, []):
                if len(selected) >= question_count:
                    break
                _append_selected_question(selected, used, question, state)
    return selected[:question_count]


def _selection_quotas(
    groups: dict[str, list[dict[str, Any]]],
    policy: dict[str, Any],
    question_count: int,
    priority: list[str],
) -> dict[str, int]:
    available = [key for key in priority if groups.get(key)]
    quotas = {key: 0 for key in groups}
    remaining = question_count
    if question_count >= len(available):
        for key in available:
            quotas[key] = 1
        remaining -= len(available)
    if remaining <= 0:
        return quotas
    ratios = {
        "easy": _coerce_weight(policy.get("easy_ratio"), default=0.3),
        "normal": _coerce_weight(policy.get("normal_ratio"), default=0.5),
        "hard": _coerce_weight(policy.get("hard_ratio"), default=0.2),
    }
    remainders: list[tuple[float, str]] = []
    for key in priority:
        target = ratios[key] * remaining
        add = int(target)
        quotas[key] += add
        remainders.append((target - add, key))
    assigned = sum(quotas.values())
    for _fraction, key in sorted(remainders, reverse=True):
        if assigned >= question_count:
            break
        quotas[key] += 1
        assigned += 1
    return quotas


def _append_selected_question(
    selected: list[dict[str, Any]],
    used: set[str],
    question: dict[str, Any],
    state: OverallState,
) -> None:
    key = _question_identifier(question)
    if key in used:
        return
    used.add(key)
    item = dict(question)
    item["question_source"] = "course_resources"
    selected.extend(_normalize_progress_questions([item], state))


def _question_identifier(question: dict[str, Any]) -> str:
    return str(question.get("question_id") or question.get("id") or question.get("stem") or question.get("question_text") or "")


def _difficulty_priority(value: Any) -> list[str]:
    target = _difficulty_key(value)
    if target == "hard":
        return ["hard", "normal", "easy"]
    if target == "easy":
        return ["easy", "normal", "hard"]
    return ["normal", "easy", "hard"]


def _difficulty_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"hard", "difficult", "advanced", "高", "困难", "较难", "提升"}:
        return "hard"
    if normalized in {"easy", "beginner", "basic", "低", "简单", "基础"}:
        return "easy"
    return "normal"


def _fallback_personalized_materials(state: OverallState) -> dict[str, Any]:
    materials = state.get("progress_patch_materials") if isinstance(state.get("progress_patch_materials"), dict) else {}
    result: dict[str, Any] = {}
    for key, material in materials.items():
        if not isinstance(material, dict):
            continue
        payload = material.get("payload") if isinstance(material.get("payload"), dict) else {}
        result[key] = {
            "title": material.get("title") or _title_for(state, key),
            "summary": material.get("summary") or "",
            "base_content": payload.get("base_content") or "",
            "knowledge_gap_patches": payload.get("knowledge_gap_patches") or [],
            "learning_guidance": "已根据学习画像调整表达方式，知识内容仍以章节基础讲义和补充内容为依据。",
        }
    return result


def _merge_progress_personalized_materials(state: OverallState, data: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_personalized_materials(state)
    raw_materials = data.get("materials") if isinstance(data.get("materials"), dict) else data
    if not isinstance(raw_materials, dict):
        raw_materials = {}
    result = {}
    for key, fallback_material in fallback.items():
        llm_material = raw_materials.get(key) if isinstance(raw_materials.get(key), dict) else {}
        merged = dict(fallback_material)
        for field in ("title", "summary", "learning_guidance"):
            value = llm_material.get(field)
            if value:
                merged[field] = value
        if llm_material.get("base_content"):
            merged["base_content"] = llm_material["base_content"]
        if llm_material.get("knowledge_gap_patches"):
            merged["knowledge_gap_patches"] = llm_material["knowledge_gap_patches"]
        if not merged.get("base_content"):
            merged["base_content"] = fallback_material.get("base_content") or ""
        if not merged.get("knowledge_gap_patches"):
            merged["knowledge_gap_patches"] = fallback_material.get("knowledge_gap_patches") or []
        merged["title"] = _student_facing_title(str(merged.get("title") or ""), state, key)
        if not _contains_chinese(str(merged.get("summary") or "")):
            merged["summary"] = _summary_for(key)
        if not _contains_chinese(str(merged.get("learning_guidance") or "")):
            merged["learning_guidance"] = fallback_material.get("learning_guidance") or "请按照章节顺序完成学习。"
        merged["base_content"] = _student_facing_markdown(str(merged.get("base_content") or ""))
        result[key] = merged
    return result


def _student_facing_base_materials(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        result[str(key)] = _student_facing_markdown(item) if isinstance(item, str) else item
    return result


def _student_facing_patch_materials(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(item, dict):
            continue
        material = dict(item)
        payload = dict(material.get("payload")) if isinstance(material.get("payload"), dict) else {}
        payload["base_content"] = _student_facing_markdown(str(payload.get("base_content") or ""))
        material["payload"] = payload
        result[str(key)] = material
    return result


def _student_facing_markdown(content: str) -> str:
    lines = str(content or "").replace("\r\n", "\n").split("\n")
    result: list[str] = []
    skipped_heading_level: int | None = None
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if skipped_heading_level is not None:
            if not heading or len(heading.group(1)) > skipped_heading_level:
                continue
            skipped_heading_level = None
        if heading and _is_internal_authoring_heading(heading.group(2)):
            skipped_heading_level = len(heading.group(1))
            continue
        if _is_internal_authoring_line(line):
            continue
        result.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(result)).strip()


def _is_internal_authoring_heading(value: str) -> bool:
    normalized = re.sub(r"[`*_\s]", "", str(value)).lower()
    return any(
        marker in normalized
        for marker in ("个性化融合建议", "内部说明", "编写说明", "生成说明", "authoringnotes")
    )


def _is_internal_authoring_line(value: str) -> bool:
    normalized = re.sub(r"[`*_\s]", "", str(value)).lower()
    if re.match(r"^\s*(?:[-*]\s*)?(?:patch\s*id|reason|evidence(?:_refs)?|source_file)\s*:", str(value), re.I):
        return True
    return any(
        marker in normalized
        for marker in (
            "人工参考讲义",
            "personalization_node",
            "生成节点使用本讲义",
            "提供稳定的高质量底稿",
            "implementation-facing",
            "检索文件",
            "evidencerefs",
            "sourcefile",
        )
    )


def _student_facing_title(value: str, state: OverallState, kind: str) -> str:
    title = str(value or "").strip()
    replacements = {"lecture": "讲义", "practice": "实训资料", "quiz": "测试题"}
    for source, target in replacements.items():
        title = re.sub(rf"\b{source}\b", target, title, flags=re.I)
    return title if _contains_chinese(title) else _title_for(state, kind)


def _contains_chinese(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value)))


def _summary_for(kind: str) -> str:
    return {
        "lecture": "本讲义由章节基础内容和针对当前知识漏洞的补充内容组成。",
        "practice": "本实训资料由章节基础内容和针对当前知识漏洞的补充内容组成。",
    }.get(kind, "本资料根据当前章节内容生成。")


def _normalize_progress_questions(questions: list[dict[str, Any]], state: OverallState) -> list[dict[str, Any]]:
    normalized = []
    for index, question in enumerate(questions, start=1):
        item = dict(question)
        item.setdefault("question_id", f"q_{state.get('chapter_id')}_{index:03d}".replace(".", "_"))
        item["knowledge_points"] = _normalize_knowledge_points(item.get("knowledge_points"), state)
        item["core_exam_points"] = _clean_string_list(item.get("core_exam_points")) or [
            str((state.get("chapter_focus") or {}).get("summary") or state.get("chapter_id") or "")
        ]
        normalized.append(item)
    return normalized


def _normalize_typed_questions(questions: list[dict[str, Any]], state: OverallState) -> list[dict[str, Any]]:
    return [_normalize_question_for_schema(question, {}, state, index)[0] for index, question in enumerate(questions, start=1)]


def _quiz_slots_from_state(state: OverallState) -> list[dict[str, Any]]:
    value = state.get("quiz_blueprint_slots")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    blueprint = state.get("quiz_generation_blueprint") if isinstance(state.get("quiz_generation_blueprint"), dict) else {}
    slots = blueprint.get("slots")
    return [item for item in slots if isinstance(item, dict)] if isinstance(slots, list) else []


def _normalize_question_for_schema(
    question: dict[str, Any],
    slot: dict[str, Any],
    state: OverallState,
    index: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors = []
    item = dict(question)
    question_type = _clean_question_type(slot.get("question_type") or item.get("question_type") or item.get("type"))
    sequence = _int_or_default(slot.get("sequence") or item.get("sequence"), index)
    item["sequence"] = sequence
    item.setdefault("question_id", f"q_{state.get('chapter_id')}_{sequence:03d}".replace(".", "_"))
    item["question_type"] = question_type
    item["stem"] = str(item.get("stem") or item.get("question") or "").strip()
    item["difficulty"] = str(slot.get("difficulty") or item.get("difficulty") or "easy")
    item["points"] = _coerce_points(slot.get("points") if slot.get("points") is not None else item.get("points"), question_type, item["difficulty"])
    item["capability_dimension"] = str(slot.get("capability_dimension") or item.get("capability_dimension") or "").strip() or QUIZ_CAPABILITY_DIMENSIONS[(sequence - 1) % len(QUIZ_CAPABILITY_DIMENSIONS)]
    item["question_purpose"] = str(slot.get("question_purpose") or item.get("question_purpose") or item.get("purpose") or "chapter_core")
    related_gap_ids = _clean_string_list(item.get("related_gap_ids"))
    if item["question_purpose"] == "gap_remediation" and not related_gap_ids:
        related_gap_ids = _clean_string_list(slot.get("related_gap_ids")) or _related_gap_ids(state)
    item["related_gap_ids"] = related_gap_ids
    item["knowledge_points"] = _normalize_knowledge_points(item.get("knowledge_points"), state)
    item["core_exam_points"] = _clean_string_list(item.get("core_exam_points")) or [
        str((state.get("chapter_focus") or {}).get("summary") or state.get("chapter_id") or "")
    ]
    item["explanation"] = str(item.get("explanation") or item.get("detailed_explanation") or "").strip()
    item["concise_explanation"] = str(item.get("concise_explanation") or item.get("explanation") or "").strip()
    item["detailed_explanation"] = str(item.get("detailed_explanation") or item.get("explanation") or "").strip()
    if question_type == "true_false":
        item["options"] = ["正确", "错误"]
        item["answer"] = _normalize_true_false_answer(item.get("answer")) or _normalize_true_false_answer(
            item.get("reference_answer")
        )
        item["reference_answer"] = "正确" if item["answer"] == "A" else "错误" if item["answer"] == "B" else ""
        if item["answer"] not in {"A", "B"}:
            errors.append({"sequence": sequence, "reason": "invalid_true_false_answer"})
    elif question_type == "single_choice":
        options = _clean_string_list(item.get("options"))
        if len(options) < 2:
            errors.append({"sequence": sequence, "reason": "single_choice_options_missing"})
        item["options"] = options[:4]
        item["answer"] = _normalize_choice_answer(item.get("answer"), item["options"])
        item["reference_answer"] = str(item.get("reference_answer") or item.get("answer") or "").strip()
    elif question_type in {"cloze", "short_answer"}:
        item["options"] = []
        item["answer"] = str(item.get("answer") or item.get("reference_answer") or "").strip()
        item["reference_answer"] = str(item.get("reference_answer") or item.get("answer") or "").strip()
        if not item["reference_answer"]:
            errors.append({"sequence": sequence, "reason": f"{question_type}_reference_answer_missing"})
        if question_type == "short_answer":
            item["scoring_rubric"] = _normalize_scoring_rubric(item.get("scoring_rubric"), item["points"])
            if not item["scoring_rubric"].get("key_points"):
                errors.append({"sequence": sequence, "reason": "short_answer_rubric_missing"})
    return item, errors


def _clean_question_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in set(QUIZ_TYPE_ORDER) else "single_choice"


def _coerce_points(value: Any, question_type: str, difficulty: str) -> float:
    try:
        points = float(value)
    except (TypeError, ValueError):
        points = _points_for(question_type, difficulty)
    return min(max(points, 0.0), 100.0)


def _normalize_choice_answer(value: Any, options: list[str]) -> str:
    raw = str(value or "").strip().upper()
    if re.fullmatch(r"[A-Z]", raw):
        return raw
    for index, option in enumerate(options):
        if str(value or "").strip() == option:
            return chr(ord("A") + index)
    return raw[:1] if raw else ""


def _normalize_true_false_answer(value: Any) -> str:
    token = re.sub(r"[\s。．，,：:；;！!？?（）()【】\[\]]", "", str(value or "").strip().lower())
    if token in {"a", "正确", "对", "是", "true", "yes", "1", "√"}:
        return "A"
    if token in {"b", "错误", "错", "否", "false", "no", "0", "×", "x"}:
        return "B"
    return ""


def _quiz_evidence_refs(state: OverallState) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in ("quiz_rag_package", "rag_package"):
        package = state.get(key)
        evidence = package.get("evidence") if isinstance(package, dict) else []
        for item in evidence if isinstance(evidence, list) else []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source_file") or item.get("source_doc") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()
            identity = (source, chunk_id)
            if not (source or chunk_id) or identity in seen:
                continue
            seen.add(identity)
            refs.append({"source_doc": source, "chunk_id": chunk_id})
    reference_quiz = state.get("reference_quiz")
    questions = reference_quiz.get("questions") if isinstance(reference_quiz, dict) else []
    for index, question in enumerate(questions if isinstance(questions, list) else [], start=1):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id") or f"question_{index:04d}")
        identity = ("reference_quiz", question_id)
        if identity in seen:
            continue
        seen.add(identity)
        refs.append({"source_doc": "reference_quiz", "chunk_id": f"reference_quiz:{question_id}"})
    return refs[:50]


def _normalize_scoring_rubric(value: Any, points: float) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"key_points": []}
    key_points = []
    raw_points = value.get("key_points")
    if isinstance(raw_points, list):
        for index, item in enumerate(raw_points, start=1):
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or item.get("text") or "").strip()
            if not description:
                continue
            key_points.append(
                {
                    "id": str(item.get("id") or f"kp_{index}"),
                    "description": description,
                    "points": _coerce_points(item.get("points"), "short_answer", "normal"),
                }
            )
    if not key_points and points > 0:
        description = str(value.get("description") or "").strip()
        if description:
            key_points.append({"id": "kp_1", "description": description, "points": points})
    result = dict(value)
    result["key_points"] = key_points
    if isinstance(value.get("required_terms"), list):
        result["required_terms"] = _clean_string_list(value.get("required_terms"))
    return result


def _normalize_knowledge_points(value: Any, state: OverallState) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        value = []
    result = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "").strip()
            point_id = str(item.get("id") or "").strip() or _knowledge_point_id(name, state, index)
            result.append(
                {
                    "id": point_id,
                    "name": name or point_id,
                    "chapter_id": str(item.get("chapter_id") or state.get("chapter_id") or ""),
                    "weight": _coerce_weight(item.get("weight"), default=1.0 / max(len(value), 1)),
                }
            )
        else:
            name = str(item).strip()
            if name:
                result.append(
                    {
                        "id": _knowledge_point_id(name, state, index),
                        "name": name,
                        "chapter_id": str(state.get("chapter_id") or ""),
                        "weight": 1.0 / max(len(value), 1),
                    }
                )
    if result:
        return result
    focus = str((state.get("chapter_focus") or {}).get("summary") or state.get("chapter_id") or "chapter_focus")
    return [{"id": _knowledge_point_id(focus, state, 1), "name": focus, "chapter_id": str(state.get("chapter_id") or ""), "weight": 1.0}]


def _knowledge_point_id(name: str, state: OverallState, index: int) -> str:
    base = safe_segment(str(name).lower()) or f"point_{index}"
    return f"{safe_segment(str(state.get('course_id') or 'course'))}.{safe_segment(str(state.get('chapter_id') or 'chapter'))}.{base}"


def _coerce_weight(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 0.0), 1.0)


def _save_progress_markdown(state: OverallState, output: dict[str, Any], *, content_type: str) -> dict[str, Any]:
    artifact_type = "practice_guide" if content_type == "practice" else content_type
    return save_generated_artifact(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or ""),
        artifact_type=artifact_type,
        title=str(output.get("title") or artifact_type),
        markdown_content=_markdown_for_progress_output(output),
        export_formats=[],
        metadata={
            "course_id": str(state.get("course_id") or ""),
            "chapter_id": str(state.get("chapter_id") or ""),
            "content_type": content_type,
            "source": "personalization_node",
        },
        storage_root=state.get("_storage_root"),
    )


def _markdown_for_progress_output(output: dict[str, Any]) -> str:
    lines = [f"# {output.get('title') or '个性化学习资料'}", ""]
    summary = str(output.get("summary") or "")
    if summary:
        lines.extend([summary, ""])
    base = str(output.get("base_content") or "")
    if base:
        lines.extend(["## 章节基础讲义", "", base, ""])
    patches = output.get("knowledge_gap_patches")
    if isinstance(patches, list) and patches:
        lines.extend(["## 知识漏洞补充", ""])
        for index, patch in enumerate(patches, start=1):
            if not isinstance(patch, dict):
                continue
            target_section = str(patch.get("target_section") or "").strip()
            heading = target_section if _contains_chinese(target_section) else f"知识点补充 {index}"
            content = _student_facing_markdown(str(patch.get("content") or ""))
            lines.extend(
                [
                    f"### {heading}",
                    "",
                    content,
                    "",
                ]
            )
    guidance = output.get("learning_guidance")
    if guidance:
        lines.extend(["## 个性化学习建议", "", str(guidance), ""])
    return "\n".join(lines).strip() + "\n"


def _resource_paths_from_assets(assets: dict[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for group, value in assets.items():
        if isinstance(value, dict):
            for key, ref in value.items():
                if isinstance(ref, dict) and ref.get("path"):
                    paths[f"{group}.{key}"] = str(ref["path"])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    for key, ref in item.items():
                        if isinstance(ref, dict) and ref.get("path"):
                            paths[f"{group}.{index}.{key}"] = str(ref["path"])
    return paths


def _read_asset_content(asset: Any) -> str:
    if not isinstance(asset, dict) or not asset.get("path") or not asset.get("exists", True):
        return ""
    path = Path(str(asset["path"]))
    try:
        return path.read_text(encoding="utf-8") if path.exists() and path.is_file() else ""
    except OSError:
        return ""


def _read_json_file(path_value: Any) -> dict[str, Any]:
    try:
        path = Path(str(path_value))
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text_file(path_value: Any) -> str:
    try:
        path = Path(str(path_value))
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def _read_jsonl_file(path_value: Any) -> list[dict[str, Any]]:
    path = Path(str(path_value))
    if not path.exists():
        return []
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
    except (OSError, json.JSONDecodeError):
        return events
    return events


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
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


def _human_message(content: str) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _clean_string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _without_query_overlap(primary: list[str], excluded: list[str]) -> list[str]:
    excluded_normalized = {_normalize_query_for_compare(item) for item in excluded}
    result = []
    seen = set()
    for item in primary:
        query = str(item).strip()
        normalized = _normalize_query_for_compare(query)
        if not query or normalized in excluded_normalized or normalized in seen:
            continue
        result.append(query)
        seen.add(normalized)
    return result


def _normalize_query_for_compare(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _average_profile_score(profile_score: dict[str, Any], profile_context: dict[str, Any]) -> float:
    overall = _normalized_capability_score(profile_score.get("overall"))
    if overall is not None:
        return overall

    dimensions = profile_score.get("dimensions") if isinstance(profile_score.get("dimensions"), dict) else {}
    dimension_scores = [
        score
        for score in (_normalized_capability_score(value) for value in dimensions.values())
        if score is not None and score > 0.0
    ]
    if dimension_scores:
        return round(sum(dimension_scores) / len(dimension_scores), 4)

    assessment = profile_context.get("capability_assessment") if isinstance(profile_context.get("capability_assessment"), dict) else {}
    score_map = assessment.get("score_map") if isinstance(assessment.get("score_map"), dict) else {}
    score_map_values = []
    for dimension in QUIZ_CAPABILITY_DIMENSIONS:
        assessed = _normalized_capability_score(score_map.get(dimension))
        provisional = _normalized_capability_score(score_map.get(f"{dimension}_provisional"))
        if assessed is not None and assessed > 0.0:
            score_map_values.append(assessed)
        elif provisional is not None and provisional > 0.0:
            score_map_values.append(provisional)
    if score_map_values:
        return round(sum(score_map_values) / len(score_map_values), 4)

    return 0.5


def _normalized_capability_score(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    if parsed > 1.0:
        parsed = parsed / 100.0
    return min(max(parsed, 0.0), 1.0)


def _first_focus(focus_items: list[Any], category: str) -> dict[str, Any]:
    for item in focus_items:
        if isinstance(item, dict) and str(item.get("category") or "") == category:
            return item
    return next((item for item in focus_items if isinstance(item, dict)), {})


def _focus_keywords(focus_item: dict[str, Any]) -> list[str]:
    keywords = focus_item.get("rag_keywords")
    if isinstance(keywords, list):
        return [str(item).strip() for item in keywords if str(item).strip()]
    return [str(focus_item.get("description") or focus_item.get("name") or "").strip()]


def _title_for(state: OverallState, kind: str) -> str:
    stage = state.get("learning_stage") if isinstance(state.get("learning_stage"), dict) else {}
    chapter_title = str(stage.get("chapter_title") or (state.get("chapter_manifest") or {}).get("title") or state.get("chapter_id") or "")
    kind_title = {"lecture": "讲义", "practice": "实训资料", "quiz": "测试题"}.get(kind, "学习资料")
    return f"{chapter_title}{kind_title}".strip()
