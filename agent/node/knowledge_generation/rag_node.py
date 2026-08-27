from __future__ import annotations

import json
import re
from typing import Any

from dotenv import load_dotenv

from agent.rag.config import RagConfig
from agent.rag.schemas import RagPackage
from agent.rag.simple_retriever import SimpleResourceRetriever
from agent.state import OverallState
from agent.node.node_logging import log_node_runtime


load_dotenv(override=True)

_rag_llm_model: Any | None = None


@log_node_runtime("rag_node")
def rag_node(state: OverallState) -> OverallState:
    questions = _questions_from_state(state)
    retriever = state.get("_rag_retriever") or SimpleResourceRetriever()
    package = retriever.retrieve(questions)

    llm_raw_output = ""
    if package.evidence:
        llm = state.get("_rag_llm") or _default_rag_llm()
        response = llm.invoke([_human_message(build_rag_prompt(state, package))])
        llm_raw_output = str(response.content)
        package = enrich_package_with_llm(package, llm_raw_output)

    return {
        "rag_package": package.model_dump(mode="json"),
        "rag_llm_raw_output": llm_raw_output,
    }


def build_rag_prompt(state: OverallState, package: RagPackage) -> str:
    evidence_lines = []
    for index, item in enumerate(package.evidence, start=1):
        evidence_lines.append(
            f"[{index}] source={item.source_file}; chunk={item.chunk_id}; score={item.score}\n{item.text}"
        )
    evidence_text = "\n\n".join(evidence_lines)
    return f"""
你是一个面向专业资料库的 RAG Agent。
你只能依据 evidence 回答，不要编造 evidence 中没有出现的事实。
如果证据不足，请返回 next_action 为 need_more_evidence。
请只返回 JSON，不要 Markdown。

JSON 格式:
{{
  "answer": "基于证据的回答",
  "confidence": 0.0,
  "warnings": [],
  "next_action": "use_as_grounded_context"
}}

task:
{state.get("task") or state.get("raw_prompt") or ""}

queries:
{json.dumps(_questions_from_state(state), ensure_ascii=False)}

evidence:
{evidence_text}
""".strip()


def enrich_package_with_llm(package: RagPackage, llm_output: str) -> RagPackage:
    data = _load_json_object(llm_output)
    answer = _clean_string(data.get("answer"))
    if answer:
        package.answer = answer

    confidence = _coerce_confidence(data.get("confidence"))
    if confidence is not None:
        package.confidence = confidence

    warnings = data.get("warnings")
    if isinstance(warnings, list):
        package.warnings = [str(item) for item in warnings if str(item).strip()]

    next_action = _clean_string(data.get("next_action"))
    if next_action in {"use_as_grounded_context", "need_more_evidence"}:
        package.next_action = next_action

    return package


def _questions_from_state(state: OverallState) -> list[str]:
    questions = state.get("rag_questions") or []
    clean_questions = [str(item).strip() for item in questions if str(item).strip()]
    if clean_questions:
        return clean_questions
    fallback = state.get("task") or state.get("raw_prompt") or state.get("task_draft") or ""
    return [str(fallback).strip()] if str(fallback).strip() else []


def _default_rag_llm() -> Any:
    global _rag_llm_model
    if _rag_llm_model is None:
        from langchain_deepseek import ChatDeepSeek

        _rag_llm_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
    return _rag_llm_model


def _human_message(content: str) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


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


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coerce_confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(parsed, 0.0), 1.0)
