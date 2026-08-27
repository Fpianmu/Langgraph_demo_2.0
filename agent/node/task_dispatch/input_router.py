from __future__ import annotations

import json
import re
from typing import Any

from dotenv import load_dotenv
from langgraph.types import Command

from agent.state import OverallState
from agent.node.node_logging import log_node_runtime

load_dotenv(override=True)




model: Any | None = None


@log_node_runtime("input_router")
def router_input(state: OverallState) -> Command[str]:
    raw_prompt = _prompt_from_state(state)
    if _operation_review_intent_from_state(state):
        route = "learning_status_router"
        return Command(
            update={
                "input_route": route,
                "learning_status_intent": "feedback",
                "operation_review_intent": "submit_review",
                "task": raw_prompt or "operation review submission",
                "rag_questions": [],
                "llm_raw_output": "",
                "task_constraints": {
                    "source": "operation_review_router",
                    "uses_llm": False,
                    "query_count": 0,
                },
            },
            goto=route,
        )
    if _cnc_simulation_intent_from_state(state):
        route = "learning_status_router"
        return Command(
            update={
                "input_route": route,
                "learning_status_intent": "feedback",
                "cnc_feedback_intent": "submit_simulation_review",
                "task": raw_prompt or "cnc simulation submission",
                "rag_questions": [],
                "llm_raw_output": "",
                "task_constraints": {
                    "source": "cnc_simulation_router",
                    "uses_llm": False,
                    "query_count": 0,
                },
            },
            goto=route,
        )
    if _explicit_feedback_context_from_state(state):
        route = "learning_status_router"
        return Command(
            update={
                "input_route": route,
                "learning_status_intent": "feedback",
                "task": raw_prompt or "feedback context submission",
                "rag_questions": [],
                "llm_raw_output": "",
                "task_constraints": {
                    "source": "feedback_context_router",
                    "uses_llm": False,
                    "query_count": 0,
                },
            },
            goto=route,
        )
    response = _model_from_state(state).invoke([_human_message(build_input_prompt(raw_prompt))])
    llm_output = str(response.content)
    parsed = parse_llm_input_output(llm_output, raw_prompt)
    route = _route_from_state(state)
    learning_status_intent = _learning_status_intent_from_state(state)
    prompt_update = _generation_prompt_update(state, parsed["task"], route)
    rag_questions = parsed["rag_questions"] if route == "rag_node" else []

    update = {
            "input_route": route,
            "learning_status_intent": learning_status_intent,
            "task": parsed["task"],
            "rag_questions": rag_questions,
            "llm_raw_output": llm_output,
            "task_constraints": {
                "source": "llm_input_processor",
                "uses_llm": True,
                "query_count": len(rag_questions),
            },
        }
    update.update(prompt_update)
    return Command(update=update, goto=route)


def input_router(state: OverallState) -> Command[str]:
    return router_input(state)


def _route_from_state(state: OverallState) -> str:
    if _operation_review_intent_from_state(state):
        return "learning_status_router"
    if _learning_status_intent_from_state(state):
        return "learning_status_router"
    return "rag_node"


def _operation_review_intent_from_state(state: OverallState) -> str:
    explicit_intent = _normalized_text(state.get("operation_review_intent"))
    if explicit_intent in {"submit_review", "operation_review"}:
        return "submit_review"

    content_type = _normalized_text(state.get("content_type"))
    if content_type in {"operation_review", "machining_review", "operation_submission"}:
        return "submit_review"

    prompt_text = _normalized_text(state.get("raw_prompt") or state.get("task_draft"))
    if _has_any(prompt_text, ("operation_review", "machining_review", "上机审查", "加工结果审查")):
        return "submit_review"
    return ""


def _cnc_simulation_intent_from_state(state: OverallState) -> bool:
    explicit_intent = _normalized_text(state.get("cnc_feedback_intent"))
    if explicit_intent in {"submit_simulation_review", "cnc_simulation", "cnc_submission"}:
        return True

    content_type = _normalized_text(state.get("content_type"))
    if content_type in {
        "cnc_simulation",
        "cnc_submission",
        "simulation_result",
        "cnc_feedback",
    }:
        return True

    chapter_id = str(state.get("chapter_id") or "").strip()
    if not chapter_id.startswith("4."):
        return False

    return bool(state.get("source_code") or state.get("hnc_code"))


def _explicit_feedback_context_from_state(state: OverallState) -> bool:
    if _learning_status_intent_from_state(state) != "feedback":
        return False
    return bool(
        state.get("feedback_source_type")
        or state.get("attempt_id")
        or state.get("session_id")
        or state.get("qa_session_id")
        or (state.get("artifact_id") and state.get("chapter_id"))
    )


def _learning_status_intent_from_state(state: OverallState) -> str:
    explicit_intent = _normalized_text(state.get("learning_status_intent"))
    if explicit_intent in {"feedback", "next_step"}:
        return explicit_intent

    content_type = _normalized_text(state.get("content_type"))
    prompt_text = _normalized_text(state.get("raw_prompt") or state.get("task_draft"))
    text = f"{content_type} {prompt_text}"
    if content_type in {"quiz_result", "quiz_feedback", "qa_dialogue", "qa_feedback"}:
        return "feedback"
    if _has_any(text, ("next_step", "next", "下一步", "继续学习", "进入下一阶段", "推进学习进度")):
        return "next_step"
    if _has_any(text, ("feedback", "反馈", "意见反馈", "学情", "学习情况", "正确率", "错题", "做题结果")):
        return "feedback"
    return ""


def _generation_prompt_update(state: OverallState, task: str, route: str) -> dict[str, Any]:
    if route != "rag_node":
        return {
            "stage_generation_prompts": {},
            "qa_generation_prompt": "",
            "quiz_generation_prompt": "",
            "lecture_generation_prompt": "",
            "practice_generation_prompt": "",
        }

    kind = _generation_kind_from_state(state)
    if not kind:
        return {"stage_generation_prompts": {}}

    field_name = {
        "qa": "qa_generation_prompt",
        "quiz": "quiz_generation_prompt",
        "lecture": "lecture_generation_prompt",
        "practice": "practice_generation_prompt",
    }[kind]
    return {
        "stage_generation_prompts": {kind: task},
        field_name: task,
    }


def _generation_kind_from_state(state: OverallState) -> str:
    content_type = _normalized_text(state.get("content_type"))
    prompt_text = _normalized_text(state.get("raw_prompt") or state.get("task_draft"))
    text = f"{content_type} {prompt_text}"
    if content_type in {"quiz", "question", "questions", "题目", "问题", "出题"}:
        return "quiz"
    if content_type in {"lecture", "lesson", "讲义"}:
        return "lecture"
    if content_type in {"practice", "guide", "实操", "实操指南", "操作指南"}:
        return "practice"
    if content_type in {"qa", "answer", "问答", "问题回答", "回答"}:
        return "qa"
    if _has_any(text, ("quiz", "question", "questions", "题目", "出题", "测试题", "练习题")):
        return "quiz"
    if _has_any(text, ("lecture", "lesson", "讲义", "课程讲解", "教学材料")):
        return "lecture"
    if _has_any(text, ("practice", "guide", "实操", "操作指南", "实训")):
        return "practice"
    if _has_any(text, ("qa", "answer", "问答", "回答")):
        return "qa"
    return ""


def build_input_prompt(raw_prompt: str) -> str:
    return f"""
你是学习材料生成系统中的输入理解节点。

你的任务不是回答用户问题,也不是生成学习材料。
你只做两件事:
1. 将用户原始提示词提炼为一个精简、专业、适合放入后续生成节点 Prompt 的 task 句段。
2. 将该 task 拆解为 3 到 6 个适合 RAG 检索的具体问题。

约束:
- task 必须短,建议 15 到 40 个中文字。
- task 不要写成完整教学方案,不要包含“输出可供...使用”等系统描述。
- rag_questions 必须是可直接用于检索资料的问题。
- rag_questions 要覆盖用户问题中的关键方向,不要机械套模板。
- 不要编造用户没有提出的过细场景。
- 只返回 JSON,不要 Markdown,不要解释。

返回格式:
{{
  "task": "精简任务句段",
  "rag_questions": [
    "检索问题1",
    "检索问题2",
    "检索问题3"
  ]
}}

用户原始提示词:
{raw_prompt}
""".strip()


def parse_llm_input_output(llm_output: str, raw_prompt: str) -> dict[str, Any]:
    data = _load_json_object(llm_output)
    task = _clean_task(data.get("task"), raw_prompt)
    rag_questions = _clean_questions(data.get("rag_questions"))

    if _looks_like_meta_input_task(task, rag_questions) or _looks_unrelated_to_prompt(
        raw_prompt,
        task,
        rag_questions,
    ):
        task = _fallback_task(raw_prompt)
        rag_questions = _fallback_questions(raw_prompt, task)

    if not rag_questions:
        rag_questions = _fallback_questions(raw_prompt, task)

    return {
        "task": task,
        "rag_questions": rag_questions,
    }


def _prompt_from_state(state: OverallState) -> str:
    prompt = state.get("raw_prompt") or state.get("task_draft") or ""
    return re.sub(r"\s+", " ", str(prompt).strip())


def _model_from_state(state: OverallState) -> Any:
    return state.get("_model") or _default_model()


def _default_model() -> Any:
    global model
    if model is None:
        from langchain_deepseek import ChatDeepSeek

        model = ChatDeepSeek(
            model="deepseek-v4-flash",
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
    return model


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


def _clean_task(value: Any, raw_prompt: str) -> str:
    task = re.sub(r"\s+", " ", str(value or "").strip())
    if not task:
        task = _fallback_task(raw_prompt)
    task = task.rstrip("。.;；")
    if len(task) > 60:
        task = task[:60].rstrip("，,。.;； ")
    return task


def _clean_questions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    questions = []
    seen = set()
    for item in value:
        question = re.sub(r"\s+", " ", str(item).strip())
        if not question:
            continue
        if not question.endswith(("?", "？")):
            question = f"{question}?"
        if question not in seen:
            questions.append(question)
            seen.add(question)
        if len(questions) >= 6:
            break
    return questions


def _fallback_task(raw_prompt: str) -> str:
    prompt = re.sub(r"\s+", " ", raw_prompt.strip())
    if not prompt:
        return "提炼学习任务"
    prompt = prompt.rstrip("?？。.;；")
    if len(prompt) <= 40:
        return prompt
    return prompt[:40].rstrip("，,。.;； ")


def _fallback_questions(raw_prompt: str, task: str) -> list[str]:
    topic = task or _fallback_task(raw_prompt)
    return [
        f"{topic}涉及哪些核心概念?",
        f"{topic}有哪些关键步骤或要点?",
        f"{topic}有哪些常见错误和注意事项?",
    ]


def _looks_like_meta_input_task(task: str, rag_questions: list[str]) -> bool:
    text = f"{task} {' '.join(rag_questions)}"
    meta_keywords = (
        "用户原始提示词",
        "输入理解节点",
        "提炼任务",
        "检索问题",
        "rag检索",
        "RAG检索",
    )
    return any(keyword in text for keyword in meta_keywords)


def _looks_unrelated_to_prompt(raw_prompt: str, task: str, rag_questions: list[str]) -> bool:
    prompt_tokens = set(_semantic_tokens(raw_prompt))
    if not prompt_tokens:
        return False
    output_tokens = set(_semantic_tokens(f"{task} {' '.join(rag_questions)}"))
    if not output_tokens:
        return True
    return len(prompt_tokens & output_tokens) < 2


def _semantic_tokens(text: str) -> list[str]:
    stopwords = {
        "什么",
        "是什么",
        "哪些",
        "如何",
        "怎么",
        "为什么",
        "以及",
        "常见",
        "定义",
        "原因",
        "表现",
        "基本",
        "要求",
        "关键",
        "核心",
        "步骤",
        "要点",
    }
    words = re.findall(r"[A-Za-z0-9_]{2,}", text)
    chinese_phrases = _chinese_phrases(text)
    tokens = words + chinese_phrases
    for phrase in chinese_phrases:
        if len(phrase) > 2:
            tokens.extend(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return [token.lower() for token in tokens if token.strip() and token not in stopwords]


def _chinese_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    current: list[str] = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            current.append(char)
            continue
        if len(current) >= 2:
            phrases.append("".join(current))
        current = []
    if len(current) >= 2:
        phrases.append("".join(current))
    return phrases


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)
