from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command

from agent.state import OverallState


LearningStatusRoute = Literal[
    "feedback_node",
    "feedback_profile_context_loader_node",
    "learning_path_resolver_node",
    "workpiece_standard_loader_node",
    "quiz_feedback_context_loader_node",
    "qa_feedback_context_loader_node",
    "cnc_exercise_loader_node",
]


def learning_status_router(state: OverallState) -> Command[LearningStatusRoute]:
    intent = _intent_from_state(state)
    route = _route_from_state(state, intent)
    update: dict[str, Any] = {
        "learning_status_intent": intent,
        "learning_status_route": route,
    }
    if route == "workpiece_standard_loader_node":
        update["operation_review_intent"] = "submit_review"
    if route == "cnc_exercise_loader_node":
        update["cnc_feedback_intent"] = "submit_simulation_review"
    if route == "quiz_feedback_context_loader_node":
        update["feedback_source_type"] = "quiz_result"
    if route == "qa_feedback_context_loader_node":
        update["feedback_source_type"] = "qa_dialogue"
    return Command(update=update, goto=route)


def _intent_from_state(state: OverallState) -> str:
    explicit = _normalized_text(state.get("learning_status_intent"))
    if explicit in {"feedback", "next_step"}:
        return explicit
    content_type = _normalized_text(state.get("content_type"))
    prompt_text = _normalized_text(state.get("raw_prompt"))
    text = f"{content_type} {prompt_text}"
    if _has_any(text, ("next_step", "next", "下一步", "继续学习", "进入下一阶段", "推进学习进度")):
        return "next_step"
    return "feedback"


def _route_from_state(state: OverallState, intent: str) -> LearningStatusRoute:
    if intent == "next_step":
        return "learning_path_resolver_node"
    if _is_quiz_feedback(state):
        return "quiz_feedback_context_loader_node"
    if _is_qa_feedback(state):
        return "qa_feedback_context_loader_node"
    if _is_chapter_four_cnc_feedback(state):
        return "cnc_exercise_loader_node"
    if _is_operation_feedback(state):
        return "workpiece_standard_loader_node"
    return "feedback_profile_context_loader_node"


def _is_chapter_four_cnc_feedback(state: OverallState) -> bool:
    chapter_id = str(state.get("chapter_id") or "").strip()
    return chapter_id.startswith("4.")


def _is_operation_feedback(state: OverallState) -> bool:
    source_type = _normalized_text(state.get("feedback_source_type"))
    content_type = _normalized_text(state.get("content_type"))
    chapter_id = str(state.get("chapter_id") or "").strip()
    if source_type == "operation_review":
        return True
    if content_type in {"operation_review", "machining_review", "operation_submission"}:
        return True
    if chapter_id.startswith("5."):
        return True
    return bool(state.get("operation_review_intent"))


def _is_quiz_feedback(state: OverallState) -> bool:
    source_type = _normalized_text(state.get("feedback_source_type"))
    content_type = _normalized_text(state.get("content_type"))
    if source_type == "quiz_result":
        return True
    if content_type in {"quiz_result", "quiz_feedback"}:
        return True
    return bool(state.get("attempt_id") and (state.get("artifact_id") or state.get("question_artifact_id")))


def _is_qa_feedback(state: OverallState) -> bool:
    source_type = _normalized_text(state.get("feedback_source_type"))
    content_type = _normalized_text(state.get("content_type"))
    if source_type == "qa_dialogue":
        return True
    if content_type in {"qa_dialogue", "qa_feedback"}:
        return True
    return bool(state.get("session_id") or state.get("qa_session_id"))


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)
