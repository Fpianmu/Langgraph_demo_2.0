from __future__ import annotations

import json
import re
from typing import Any

from dotenv import load_dotenv

from agent.rag.config import RagConfig
from agent.state import OverallState
from agent.node.node_logging import log_node_runtime
from agent.tools.qa_tools import load_qa_session_context


load_dotenv(override=True)

_generation_model: Any | None = None


GENERATION_PROMPT_CONSTRAINTS = """
生成限制:
- 不要输出任何图片引用文字。
- 禁止使用“图一”“图1”“图2”“见图”“如下图”“上图”“下图”“左图”“右图”等表述。
- 如果证据中出现图片编号或图片指代，请改写为纯文本资料表述。
- 输出必须独立可读，不依赖用户查看图片、插图或示意图。
""".strip()

IMAGE_REFERENCE_REPLACEMENTS = (
    (re.compile(r"如?图\s*[一二三四五六七八九十\d]+所示[，,、：:]?"), ""),
    (re.compile(r"图\s*[一二三四五六七八九十\d]+"), "资料"),
    (re.compile(r"(见|如下|参见|参考|上|下|左|右)图"), "参考资料"),
    (re.compile(r"如图所示"), "根据资料"),
    (re.compile(r"(图片|插图|示意图)"), "资料"),
)


@log_node_runtime("question_generator")
def question_generator(state: OverallState) -> OverallState:
    task = _task(state)
    llm_data = _invoke_generation_llm(state, build_question_prompt(state))
    questions = _clean_questions(llm_data.get("questions"))
    return _material_update(
        state,
        content_type="quiz",
        title=_clean_string(llm_data.get("title")) or f"{task}测验题",
        summary=_clean_string(llm_data.get("summary")) or f"围绕{task}生成的测验题。",
        payload={"questions": questions},
    )


@log_node_runtime("lecture_generator")
def lecture_generator(state: OverallState) -> OverallState:
    task = _task(state)
    llm_data = _invoke_generation_llm(state, build_lecture_prompt(state))
    sections = _clean_sections(llm_data.get("sections"))
    if not sections:
        sections = _fallback_lecture_sections(state)
    return _material_update(
        state,
        content_type="lecture",
        title=_clean_string(llm_data.get("title")) or f"{task}讲义",
        summary=_clean_string(llm_data.get("summary")) or f"面向{task}的结构化讲义。",
        payload={"sections": sections},
    )


@log_node_runtime("practice_guide_generator")
def practice_guide_generator(state: OverallState) -> OverallState:
    task = _task(state)
    llm_data = _invoke_generation_llm(state, build_practice_prompt(state))
    payload = {
        "objectives": _clean_string_list(llm_data.get("objectives"))
        or [f"完成{task}相关的实操准备、过程检查和异常处理。"],
        "steps": _clean_string_list(llm_data.get("steps"))
        or _evidence_texts(state)[:5]
        or ["当前证据不足，需要补充知识库证据后再生成具体步骤。"],
        "checklist": _clean_string_list(llm_data.get("checklist"))
        or ["确认设备状态", "确认人员防护", "确认异常处理方式"],
        "safety_points": _clean_string_list(llm_data.get("safety_points"))
        or _evidence_texts(state)[:3]
        or ["证据不足时不得生成具体高风险操作。"],
    }
    return _material_update(
        state,
        content_type="practice",
        title=_clean_string(llm_data.get("title")) or f"{task}实操指南",
        summary=_clean_string(llm_data.get("summary")) or f"面向{task}的实操指南，强调步骤、检查点和安全边界。",
        payload=payload,
    )


def build_lecture_prompt(state: OverallState) -> str:
    task = _task(state)
    return f"""
你是机械制造课程的讲义生成节点。请根据 task 和 RAG 材料，生成一份可以直接给学生阅读的结构化讲义。

要求:
- 只依据 RAG 材料组织内容，不要编造材料中没有的事实。
- 面向初学者，先解释“为什么”，再解释“是什么”和“怎么理解”。
- 内容必须像讲义，不要只是罗列检索片段。
- 如果 RAG 材料不足，请在讲义中明确说明哪些内容证据不足，但仍要把已有证据整理清楚。
- 只返回 JSON，不要 Markdown，不要解释。
{GENERATION_PROMPT_CONSTRAINTS}

JSON 格式:
{{
  "title": "讲义标题",
  "summary": "1 到 2 句话概括本讲义",
  "sections": [
    {{"heading": "学习目标", "content": "完整段落"}},
    {{"heading": "核心概念讲解", "content": "完整段落"}},
    {{"heading": "关键原理与组成关系", "content": "完整段落"}},
    {{"heading": "初学者易错点", "content": "完整段落"}},
    {{"heading": "本节小结", "content": "完整段落"}}
  ]
}}

task:
{task}

RAG answer:
{_rag_answer(state)}

RAG evidence:
{_evidence_for_prompt(state)}
""".strip()


def build_practice_prompt(state: OverallState) -> str:
    task = _task(state)
    return f"""
你是机械制造课程的实训资料生成节点。请根据 task 和 RAG 材料，生成一份可以直接给学生执行或预习的实训资料。

要求:
- 只依据 RAG 材料组织内容，不要编造材料中没有的设备参数、危险动作或操作权限。
- 输出应包括训练目标、操作步骤、检查清单和安全要点。
- 面向初学者，步骤要清楚，安全边界要明确。
- 如果 RAG 材料不足，请把不确定项写成“需教师确认/需补充资料”，不要硬编。
- 只返回 JSON，不要 Markdown，不要解释。
{GENERATION_PROMPT_CONSTRAINTS}

JSON 格式:
{{
  "title": "实训资料标题",
  "summary": "1 到 2 句话概括本实训",
  "objectives": ["目标 1", "目标 2"],
  "steps": ["步骤 1", "步骤 2", "步骤 3"],
  "checklist": ["检查项 1", "检查项 2"],
  "safety_points": ["安全要点 1", "安全要点 2"]
}}

task:
{task}

RAG answer:
{_rag_answer(state)}

RAG evidence:
{_evidence_for_prompt(state)}
""".strip()


def build_question_prompt(state: OverallState) -> str:
    task = _task(state)
    knowledge_point_rules = """
knowledge_points 规则:
- 每道题必须标注 1 到 3 个核心考点。
- 每个考点必须包含 id、name、chapter_id、weight。
- id 使用稳定机器可读格式，例如 cnc_lathe.basic_motion.main_motion。
- name 使用适合前端展示的简短考点名称。
- weight 使用 0 到 1 的小数，同一题所有考点 weight 建议总和为 1。
""".strip()
    capability_rules = """
能力维度与核心考点规则:
- 每道题必须标注 capability_dimension，取值只能是 safety、foundations、process_planning、programming、machining_operation、quality_control、maintenance、advanced_manufacturing 之一。
- 每道题必须标注 core_exam_points，列出 1 到 3 个学生可见的核心考点。
- question_type 可使用 single_choice、true_false、cloze、short_answer；如果没有明确要求，优先 single_choice。
""".strip()
    return f"""
你是机械制造课程的测验题生成节点。请根据 task 和 RAG 材料，生成可以直接给学生使用的测验题。

要求:
- 必须调用并依据 RAG 材料生成题目，不要使用固定模板题。
- 题目要覆盖核心概念、易错点和安全边界。
- 每道题必须有题干、题型、能力维度、核心考点、选项、标准答案、解析和难度。
- 选项建议 4 个，answer 使用 A/B/C/D。
- 如果 RAG 材料不足，请围绕已有证据出题，并在解析中说明证据边界。
- 只返回 JSON，不要 Markdown，不要解释。
{GENERATION_PROMPT_CONSTRAINTS}

JSON 格式:
{{
  "title": "测验题标题",
  "summary": "1 到 2 句话概括本测验",
  "questions": [
    {{
      "stem": "题干",
      "question_type": "single_choice",
      "options": ["选项 A", "选项 B", "选项 C", "选项 D"],
      "answer": "A",
      "explanation": "解析",
      "difficulty": "easy",
      "points": 1,
      "capability_dimension": "foundations",
      "knowledge_points": [
        {{"id": "cnc_lathe.chapter.concept", "name": "核心考点", "chapter_id": "1.1", "weight": 1.0}}
      ],
      "core_exam_points": ["核心考点"]
    }}
  ]
}}

{knowledge_point_rules}
{capability_rules}

task:
{task}

RAG answer:
{_rag_answer(state)}

RAG evidence:
{_evidence_for_prompt(state)}
""".strip()


def build_qa_prompt(state: OverallState) -> str:
    task = _task(state)
    raw_question = str(state.get("raw_prompt") or task).strip()
    qa_context = _qa_context_text(state)
    return f"""
你是机械制造课程的问答生成节点。请根据用户问题、task 和 RAG 材料，生成可以直接回复用户的专业回答。

要求:
- 必须调用并依据 RAG 材料生成回答，不要直接复制 RAG answer。
- 回答要结构清楚，适合初学者阅读。
- 如果证据不足，要明确说明“资料中未充分覆盖”的部分，不要编造。
- follow_ups 给出 1 到 3 个适合继续学习的问题。
- 只返回 JSON，不要 Markdown，不要解释。
{GENERATION_PROMPT_CONSTRAINTS}

JSON 格式:
{{
  "title": "问答标题",
  "summary": "1 到 2 句话概括回答内容",
  "question": "用户问题",
  "answer": "完整回答",
  "follow_ups": ["追问 1", "追问 2"]
}}

user_question:
{raw_question}

conversation_context:
{qa_context}

task:
{task}

RAG answer:
{_rag_answer(state)}

RAG evidence:
{_evidence_for_prompt(state)}
""".strip()


@log_node_runtime("qa_answer_generator")
def qa_answer_generator(state: OverallState) -> OverallState:
    task = _task(state)
    qa_context = _load_qa_context(state)
    prompt_state: OverallState = {**state, "qa_context": qa_context}
    llm_data = _invoke_generation_llm(prompt_state, build_qa_prompt(prompt_state))
    payload = {
        "question": _clean_string(llm_data.get("question")) or str(state.get("raw_prompt") or task),
        "answer": _clean_string(llm_data.get("answer")),
        "follow_ups": _clean_string_list(llm_data.get("follow_ups")),
    }
    update = _material_update(
        state,
        content_type="qa",
        title=_clean_string(llm_data.get("title")) or f"{task}问题回答",
        summary=_clean_string(llm_data.get("summary")) or f"针对{task}生成的问题回答。",
        payload=payload,
    )
    update["qa_context"] = qa_context
    return update


def _material_update(
    state: OverallState,
    *,
    content_type: str,
    title: str,
    summary: str,
    payload: dict[str, Any],
) -> OverallState:
    output = {
        "meta": {
            "request_id": str(state.get("request_id") or ""),
            "content_type": content_type,
            "status": "success",
            "retry_count": int(state.get("retry_count") or 0),
        },
        "title": title,
        "summary": summary,
        "payload": payload,
        "evidence_refs": _evidence_refs(state),
        "safety_notes": _safety_notes(state),
        "next_actions": _next_actions(state),
    }
    output = _sanitize_output(output)
    update = {
        "generated_content": output,
        "final_output": output,
    }
    update.update(_type_specific_material_update(content_type, output))
    return update


def _type_specific_material_update(content_type: str, output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    field_prefix = _field_prefix_for_content_type(content_type)
    return {
        f"generated_{field_prefix}_content": output,
        f"final_{field_prefix}_output": output,
    }


def _field_prefix_for_content_type(content_type: str) -> str:
    mapping = {
        "quiz": "question",
        "question": "question",
        "questions": "question",
        "lecture": "lecture",
        "practice": "practice_guide",
        "practice_guide": "practice_guide",
        "qa": "qa",
    }
    return mapping.get(content_type, "generated")


def _invoke_generation_llm(state: OverallState, prompt: str) -> dict[str, Any]:
    try:
        response = _model_from_state(state).invoke([_human_message(prompt)])
    except ModuleNotFoundError:
        return {}
    return _load_json_object(str(response.content))


def _model_from_state(state: OverallState) -> Any:
    return state.get("_generation_model") or state.get("_model") or _default_model()


def _default_model() -> Any:
    global _generation_model
    if _generation_model is None:
        from langchain_deepseek import ChatDeepSeek

        _generation_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
    return _generation_model


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


def _clean_string(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()) if isinstance(value, str) else ""


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _clean_string(item)
        if text:
            result.append(text)
    return result


def _clean_sections(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    sections = []
    for item in value:
        if not isinstance(item, dict):
            continue
        heading = _clean_string(item.get("heading"))
        content = _clean_string(item.get("content"))
        if heading and content:
            sections.append({"heading": heading, "content": content})
    return sections


def _clean_questions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    questions = []
    for item in value:
        if not isinstance(item, dict):
            continue
        stem = _clean_string(item.get("stem"))
        options = _clean_string_list(item.get("options"))
        answer = _clean_string(item.get("answer")).upper()
        explanation = _clean_string(item.get("explanation"))
        difficulty = _clean_string(item.get("difficulty")) or "normal"
        knowledge_points = _clean_knowledge_points(item.get("knowledge_points"))
        question_type = _clean_question_type(item.get("question_type") or item.get("type"))
        capability_dimension = _clean_capability_dimension(item.get("capability_dimension") or item.get("capabilityDimension"))
        core_exam_points = _clean_string_list(item.get("core_exam_points") or item.get("coreExamPoints"))
        points = _clean_points(item.get("points"))
        if stem and options and answer:
            question = {
                "stem": stem,
                "question_type": question_type,
                "options": options,
                "answer": answer,
                "explanation": explanation,
                "difficulty": difficulty,
                "knowledge_points": knowledge_points,
                "core_exam_points": core_exam_points,
            }
            if capability_dimension:
                question["capability_dimension"] = capability_dimension
            if points is not None:
                question["points"] = points
            questions.append(question)
    return questions


def _clean_question_type(value: Any) -> str:
    normalized = _clean_string(value).lower()
    if normalized in {"single_choice", "true_false", "cloze", "short_answer"}:
        return normalized
    return "single_choice"


def _clean_capability_dimension(value: Any) -> str:
    raw = _clean_string(value)
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "theory": "foundations",
        "operation": "machining_operation",
        "基础理论": "foundations",
        "基础识图": "foundations",
        "安全": "safety",
        "数控编程": "programming",
        "工艺规划": "process_planning",
        "操作加工": "machining_operation",
        "质量检测": "quality_control",
        "维护诊断": "maintenance",
        "先进制造": "advanced_manufacturing",
    }
    allowed = {
        "safety",
        "foundations",
        "process_planning",
        "programming",
        "machining_operation",
        "quality_control",
        "maintenance",
        "advanced_manufacturing",
    }
    return normalized if normalized in allowed else aliases.get(raw, "")


def _clean_points(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean_knowledge_points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    points = []
    seen = set()
    for item in value:
        if isinstance(item, str):
            point_id = _clean_string(item)
            name = point_id
            chapter_id = ""
            weight = 1.0
        elif isinstance(item, dict):
            point_id = _clean_string(item.get("id") or item.get("knowledge_point_id"))
            name = _clean_string(item.get("name") or item.get("concept") or point_id)
            chapter_id = _clean_string(item.get("chapter_id"))
            weight = _clean_weight(item.get("weight"))
        else:
            continue
        if not point_id and not name:
            continue
        dedupe_key = point_id or name
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        points.append(
            {
                "id": point_id,
                "name": name,
                "chapter_id": chapter_id,
                "weight": weight,
            }
        )
        if len(points) >= 3:
            break
    return points


def _clean_weight(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(max(parsed, 0.0), 1.0)


def _fallback_lecture_sections(state: OverallState) -> list[dict[str, str]]:
    task = _task(state)
    evidence = _evidence_texts(state)
    return [
        {"heading": "学习目标", "content": f"理解并掌握：{task}。"},
        {"heading": "核心知识", "content": _joined_evidence(evidence)},
        {"heading": "学习提示", "content": "先理解概念，再结合设备或案例检查每一步的依据。"},
    ]


def _rag_answer(state: OverallState) -> str:
    answer = _rag_package(state).get("answer")
    return str(answer).strip() if answer else ""


def _evidence_for_prompt(state: OverallState) -> str:
    items = _evidence_items(state)
    if not items:
        return "当前没有可用 RAG evidence。"
    lines = []
    for index, item in enumerate(items[:5], start=1):
        source = str(item.get("source_file") or item.get("source_doc") or "")
        chunk = str(item.get("chunk_id") or "")
        text = str(item.get("text") or "").strip()
        lines.append(f"[{index}] source={source}; chunk={chunk}\n{text[:1200]}")
    return "\n\n".join(lines)


def _task(state: OverallState) -> str:
    return str(state.get("task") or state.get("raw_prompt") or state.get("task_draft") or "学习任务").strip()


def _rag_package(state: OverallState) -> dict[str, Any]:
    value = state.get("rag_package")
    return value if isinstance(value, dict) else {}


def _evidence_items(state: OverallState) -> list[dict[str, Any]]:
    evidence = _rag_package(state).get("evidence")
    if not isinstance(evidence, list):
        return []
    return [item for item in evidence if isinstance(item, dict)]


def _evidence_texts(state: OverallState) -> list[str]:
    texts = []
    for item in _evidence_items(state):
        text = str(item.get("text") or "").strip()
        if text:
            texts.append(text[:260])
    return texts


def _evidence_refs(state: OverallState) -> list[dict[str, str]]:
    refs = []
    for item in _evidence_items(state):
        refs.append(
            {
                "source_doc": str(item.get("source_doc") or item.get("source_file") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "claim": str(item.get("text") or "")[:80],
            }
        )
    return refs


def _safety_notes(state: OverallState) -> list[str]:
    notes = []
    rag_warnings = _rag_package(state).get("warnings")
    if isinstance(rag_warnings, list):
        notes.extend(str(item) for item in rag_warnings if str(item).strip())
    return notes


def _next_actions(state: OverallState) -> list[str]:
    if _rag_package(state).get("next_action") == "need_more_evidence":
        return ["补充或重新检索知识库证据后再生成最终材料。"]
    return ["进入内容审查节点，检查生成材料是否完全受 RAG 证据支持。"]


def _load_qa_context(state: OverallState) -> dict[str, Any]:
    session_id = str(state.get("qa_session_id") or "").strip()
    user_id = str(state.get("user_id") or "default_user").strip()
    if not session_id:
        return {"session_id": "", "user_id": user_id, "messages": [], "context_text": ""}
    try:
        return load_qa_session_context(
            user_id=user_id,
            session_id=session_id,
            max_messages=int(state.get("qa_context_max_messages") or 20),
            storage_root=state.get("_storage_root"),
        )
    except (OSError, ValueError):
        return {"session_id": session_id, "user_id": user_id, "messages": [], "context_text": ""}


def _qa_context_text(state: OverallState) -> str:
    value = state.get("qa_context")
    if isinstance(value, dict):
        text = str(value.get("context_text") or "").strip()
        if text:
            return text
    return "No previous QA conversation context."


def _joined_evidence(evidence: list[str]) -> str:
    if not evidence:
        return "当前证据不足，需要补充或重新检索知识库。"
    return "\n".join(f"{index}. {text}" for index, text in enumerate(evidence[:5], start=1))


def _sanitize_output(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_output(item) for item in value]
    if isinstance(value, str):
        return _sanitize_image_references(value)
    return value


def _sanitize_image_references(text: str) -> str:
    result = text
    for pattern, replacement in IMAGE_REFERENCE_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"\s+", " ", result)
    result = result.replace("，。", "。").replace(",,", ",").replace("。。", "。")
    return result.strip()
