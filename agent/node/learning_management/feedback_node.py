from __future__ import annotations

import json
import logging
import re
from typing import Any

from dotenv import load_dotenv

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState


load_dotenv(override=True)

_feedback_model: Any | None = None
LOGGER = logging.getLogger("agent.feedback")


@log_node_runtime("feedback_node")
def feedback_node(state: OverallState) -> OverallState:
    blocked_result = _preflight_block_result(state)
    if blocked_result:
        return blocked_result

    raw_prompt = _feedback_text(state)
    response = _model_from_state(state).invoke([_human_message(build_feedback_prompt(state, raw_prompt))])
    llm_raw_output = str(response.content)
    suggestions = parse_feedback_llm_output(llm_raw_output)
    LOGGER.info(
        "feedback_node parsed profile suggestions user_id=%s request_id=%s "
        "capability_evidence=%d knowledge_gap_patches=%d progress_patches=%d markdown_patch=%s",
        str(state.get("user_id") or "default_user"),
        str(state.get("request_id") or ""),
        len(suggestions.get("capability_evidence") or []),
        len(suggestions.get("knowledge_gap_patches") or []),
        len(suggestions.get("progress_patches") or []),
        bool(suggestions.get("markdown_patch")),
    )

    if not _has_any_suggestion(suggestions):
        LOGGER.info(
            "feedback_node skipped profile update user_id=%s request_id=%s reason=no_valid_feedback_suggestions",
            str(state.get("user_id") or "default_user"),
            str(state.get("request_id") or ""),
        )
        return {
            "feedback_llm_raw_output": llm_raw_output,
            "profile_update_suggestions": suggestions,
            "feedback_assessment": suggestions.get("feedback_assessment") or {},
            "profile_update_result": {"accepted": False, "reason": "no_valid_feedback_suggestions"},
            "feedback_result": {
                "status": "no_update",
                "feedback_type": _feedback_type(suggestions),
                "message": "LLM 未生成可写入画像的有效建议。",
            },
        }

    packet = _build_profile_evidence_packet(state, suggestions, raw_prompt)
    LOGGER.info(
        "feedback_node built profile evidence packet user_id=%s request_id=%s source_type=%s "
        "capability_evidence=%d knowledge_gap_patches=%d progress_patches=%d",
        str(state.get("user_id") or "default_user"),
        str(state.get("request_id") or ""),
        str(packet.get("source_type") or ""),
        len(suggestions.get("capability_evidence") or []),
        len(suggestions.get("knowledge_gap_patches") or []),
        len(suggestions.get("progress_patches") or []),
    )

    return {
        "feedback_llm_raw_output": llm_raw_output,
        "profile_update_suggestions": suggestions,
        "profile_evidence_packet": packet,
        "feedback_assessment": suggestions.get("feedback_assessment") or {},
        "profile_update_result": {"accepted": False, "reason": "pending_profile_assessment_review"},
        "feedback_result": {
            "status": "pending_review",
            "feedback_type": _feedback_type(suggestions),
            "message": "已生成画像证据包，等待学情画像中间层审核。",
            "proposed_metrics": 0,
            "proposed_capability_evidence": len(suggestions.get("capability_evidence") or []),
            "proposed_knowledge_gaps": len(suggestions.get("knowledge_gap_patches") or []),
            "proposed_learning_progress": len(suggestions.get("progress_patches") or []),
        },
    }


def _preflight_block_result(state: OverallState) -> dict[str, Any]:
    user_id = str(state.get("user_id") or "").strip()
    if not user_id:
        return _blocked_feedback_result(
            reason="missing_user_id",
            feedback_type=str(state.get("feedback_source_type") or ""),
            message="feedback update requires an explicit user_id",
        )

    load_result = state.get("feedback_context_load_result")
    if isinstance(load_result, dict):
        status = str(load_result.get("status") or "").strip()
        if status and status != "success":
            return _blocked_feedback_result(
                reason="feedback_context_load_failed",
                feedback_type=str(state.get("feedback_source_type") or ""),
                message="feedback context could not be loaded, profile update skipped",
            )
    return {}


def _blocked_feedback_result(*, reason: str, feedback_type: str, message: str) -> dict[str, Any]:
    return {
        "profile_update_result": {"accepted": False, "reason": reason},
        "feedback_result": {
            "status": "no_update",
            "feedback_type": feedback_type,
            "message": message,
        },
    }


def build_feedback_prompt(state: OverallState, raw_prompt: str) -> str:
    payload = {
        "user_id": state.get("user_id") or "default_user",
        "course_id": state.get("course_id") or "",
        "chapter_id": state.get("chapter_id") or "",
        "feedback_source_type": state.get("feedback_source_type") or "",
        "feedback_context_load_result": state.get("feedback_context_load_result") or {},
        "feedback_context": state.get("feedback_context") or {},
        "raw_prompt": raw_prompt,
        "quiz_attempt": state.get("quiz_attempt") or {},
        "qa_messages": state.get("qa_messages") or [],
        "generated_materials": state.get("generated_materials") or {},
        "final_materials": state.get("final_materials") or {},
        "generated_content": state.get("generated_content") or {},
        "final_output": state.get("final_output") or {},
        "profile_context": state.get("profile_context") or {},
    }
    return f"""
Feedback taxonomy:
- quiz_result: quiz accuracy, wrong answers, and concept mastery evidence.
- qa_dialogue: QA conversation records that reveal misunderstanding or uncertainty.
- lecture_feedback: feedback about lecture difficulty, pace, depth, or coverage.
- practice_feedback: feedback about practice guide steps, safety reminders, or operability.
- mixed_feedback: two or more feedback source types appear together.
- unknown: evidence is insufficient for classification.

Required classification field:
{{
  "feedback_assessment": {{
    "feedback_type": "quiz_result|qa_dialogue|lecture_feedback|practice_feedback|mixed_feedback|unknown",
    "confidence": 0.0,
    "rationale": "why this feedback type was selected"
  }}
}}

Rules:
- QA, lecture, and practice feedback may update learning preferences, weak points, knowledge gaps, or progress; do not invent quiz accuracy.
- quiz_result may update capability_evidence, knowledge gaps, and progress from accuracy, wrong answers, and concept evidence.

你是学习画像更新节点，只负责把前端传回的学习反馈整理为可写入用户画像数据库的 JSON。

你不要生成讲义、题目或问答内容。
你只能根据输入中的正确率、错题、问答表现、学习反馈、当前课程章节，生成画像更新建议。
如果证据不足，可以返回空数组或省略对应字段。

输出必须是 JSON，不要 Markdown，不要解释。

JSON 格式:
{{
  "capability_evidence": [
    {{
      "id": "attempt_id-question_id",
      "attemptId": "attempt_id",
      "sourceType": "quiz|practice|external_assessment",
      "dimension": "safety|foundations|process_planning|programming|machining_operation|quality_control|maintenance|advanced_manufacturing",
      "topic": "主题",
      "knowledgePoint": "知识点",
      "knowledgePointId": "稳定知识点ID",
      "correct": true,
      "earned": 1,
      "possible": 1,
      "difficulty": "easy|medium|hard",
      "occurredAt": "ISO时间",
      "sourceRefs": [],
      "ragChunkIds": [],
      "questionType": "single_choice",
      "attemptNumber": 1,
      "itemRevision": "题目版本",
      "dimensionSource": "declared|keyword|fallback",
      "questionGrounded": true,
      "reviewStatus": "auto_verified|pending_review|reviewed|rejected",
      "chapterId": "章节ID",
      "objectiveIds": []
    }}
  ],
  "knowledge_gap_patches": [
    {{"concept": "知识点", "severity": "low|medium|high", "evidence": "依据", "status": "open|resolved"}}
  ],
  "progress_patches": [
    {{"course_id": "课程ID", "chapter_id": "章节ID", "status": "completed|needs_review|in_progress", "completion_rate": 0.0}}
  ],
  "markdown_patch": {{"section": "当前薄弱点", "content": "需要写入 Markdown 的简短内容"}}
}}

约束:
- completion_rate 使用 0 到 1 的小数。
- 不要编造输入中没有依据的课程章节或知识点。
- markdown_patch.content 必须简短，适合追加到用户画像 Markdown。

输入:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def parse_feedback_llm_output(llm_output: str) -> dict[str, Any]:
    data = _load_json_object(llm_output)
    suggestions: dict[str, Any] = {
        "feedback_assessment": _feedback_assessment(data.get("feedback_assessment")),
        "capability_evidence": _list_of_dicts(data.get("capability_evidence")),
        "knowledge_gap_patches": _list_of_dicts(data.get("knowledge_gap_patches")),
        "progress_patches": _list_of_dicts(data.get("progress_patches")),
    }
    markdown_patch = data.get("markdown_patch")
    if isinstance(markdown_patch, dict):
        section = str(markdown_patch.get("section") or "").strip()
        content = str(markdown_patch.get("content") or "").strip()
        if section and content:
            suggestions["markdown_patch"] = {"section": section, "content": content}
    return suggestions


def _build_profile_evidence_packet(state: OverallState, suggestions: dict[str, Any], raw_prompt: str) -> dict[str, Any]:
    assessment = suggestions.get("feedback_assessment") if isinstance(suggestions.get("feedback_assessment"), dict) else {}
    request_id = str(state.get("request_id") or "").strip()
    packet_id = request_id or f"feedback-{str(state.get('user_id') or 'default_user')}"
    return {
        "packet_id": packet_id,
        "packet_type": "profile_evidence_packet",
        "source_type": str(assessment.get("feedback_type") or state.get("feedback_source_type") or "general_feedback"),
        "source_node": "feedback_node",
        "user_id": str(state.get("user_id") or "default_user"),
        "course_id": str(state.get("course_id") or ""),
        "chapter_id": str(state.get("chapter_id") or ""),
        "task_id": str(state.get("task_id") or ""),
        "attempt_id": str(state.get("attempt_id") or request_id),
        "overall_result": "evidence_proposed",
        "confidence": assessment.get("confidence"),
        "raw_feedback": raw_prompt,
        "student_visible_feedback": "",
        "proposed_profile_changes": suggestions,
        "artifact_refs": {
            "feedback_context_paths": state.get("feedback_context_paths") or {},
            "profile_md_ref": (state.get("profile_context") or {}).get("profile_md_ref") if isinstance(state.get("profile_context"), dict) else "",
        },
    }


def _feedback_text(state: OverallState) -> str:
    prompt = state.get("raw_prompt") or state.get("task_draft") or ""
    return re.sub(r"\s+", " ", str(prompt).strip())


def _model_from_state(state: OverallState) -> Any:
    return state.get("_feedback_model") or state.get("_model") or _default_model()


def _default_model() -> Any:
    global _feedback_model
    if _feedback_model is None:
        from langchain_deepseek import ChatDeepSeek

        _feedback_model = ChatDeepSeek(
            model="deepseek-v4-flash",
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
    return _feedback_model


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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _feedback_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    allowed_types = {
        "quiz_result",
        "qa_dialogue",
        "lecture_feedback",
        "practice_feedback",
        "mixed_feedback",
        "unknown",
    }
    feedback_type = str(value.get("feedback_type") or "").strip()
    if feedback_type and feedback_type not in allowed_types:
        feedback_type = "unknown"

    result: dict[str, Any] = {}
    if feedback_type:
        result["feedback_type"] = feedback_type

    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        result["confidence"] = min(max(confidence, 0.0), 1.0)

    rationale = str(value.get("rationale") or "").strip()
    if rationale:
        result["rationale"] = rationale
    return result


def _feedback_type(suggestions: dict[str, Any]) -> str:
    assessment = suggestions.get("feedback_assessment")
    if isinstance(assessment, dict):
        return str(assessment.get("feedback_type") or "")
    return ""


def _has_any_suggestion(suggestions: dict[str, Any]) -> bool:
    return bool(
        suggestions.get("capability_evidence")
        or suggestions.get("knowledge_gap_patches")
        or suggestions.get("progress_patches")
        or suggestions.get("markdown_patch")
    )
