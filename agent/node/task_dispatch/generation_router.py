from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command

from agent.state import OverallState
from agent.node.node_logging import log_node_runtime


GenerationRoute = Literal[
    "multi_generation_node",
    "quiz_context_adapter_node",
    "question_generator",
    "lecture_generator",
    "practice_guide_generator",
    "qa_answer_generator",
]


@log_node_runtime("generation_router")
def generation_router(state: OverallState) -> Command[GenerationRoute]:
    route = _route_from_state(state)
    return Command(update={"generation_route": route}, goto=route)


def _route_from_state(state: OverallState) -> GenerationRoute:
    if _has_only_quiz_generation_prompt(state):
        return "quiz_context_adapter_node"
    if _has_generation_prompts(state):
        return "multi_generation_node"

    content_type = _normalized_text(state.get("content_type"))
    task_text = _normalized_text(state.get("task") or state.get("raw_prompt") or state.get("task_draft"))
    exact_route = _route_from_content_type(content_type)
    if exact_route is not None:
        return exact_route

    text = f"{content_type} {task_text}"

    if _has_any(text, ("quiz", "question", "questions", "题目", "问题", "出题", "测试题", "练习题", "问题生成")):
        return "question_generator"
    if _has_any(text, ("lecture", "lesson", "讲义", "课程讲解", "教学材料", "知识讲解")):
        return "lecture_generator"
    if _has_any(text, ("practice", "guide", "实操", "操作指南", "实训", "步骤指南", "训练")):
        return "practice_guide_generator"
    if _has_any(text, ("qa", "answer", "问答", "回答", "解释一下", "是什么", "为什么", "怎么")):
        return "qa_answer_generator"
    return "lecture_generator"


def _route_from_content_type(content_type: str) -> GenerationRoute | None:
    if content_type in {"quiz", "question", "questions", "问题", "题目", "出题"}:
        return "quiz_context_adapter_node"
    if content_type in {"lecture", "lesson", "讲义"}:
        return "lecture_generator"
    if content_type in {"practice", "guide", "实操", "实操指南", "操作指南"}:
        return "practice_guide_generator"
    if content_type in {"qa", "answer", "问答", "问题回答", "回答"}:
        return "qa_answer_generator"
    return None


def _has_only_quiz_generation_prompt(state: OverallState) -> bool:
    prompts = state.get("stage_generation_prompts")
    if isinstance(prompts, dict):
        filled = {str(key): value for key, value in prompts.items() if str(value).strip()}
        if set(filled) == {"quiz"}:
            return True
    if str(state.get("quiz_generation_prompt") or "").strip() and not any(
        str(state.get(key) or "").strip()
        for key in (
            "qa_generation_prompt",
            "lecture_generation_prompt",
            "practice_generation_prompt",
        )
    ):
        return True
    return False


def _has_generation_prompts(state: OverallState) -> bool:
    prompts = state.get("stage_generation_prompts")
    if isinstance(prompts, dict) and any(str(value).strip() for value in prompts.values()):
        return True
    return any(
        str(state.get(key) or "").strip()
        for key in (
            "qa_generation_prompt",
            "quiz_generation_prompt",
            "lecture_generation_prompt",
            "practice_generation_prompt",
        )
    )


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)
