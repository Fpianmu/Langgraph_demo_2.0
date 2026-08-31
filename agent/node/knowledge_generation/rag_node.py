from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.course_resources.repository import CourseResourceRepository
from agent.rag.config import RagConfig
from agent.rag.schemas import Citation, EvidenceItem, RagPackage
from agent.rag.simple_retriever import SimpleResourceRetriever
from agent.state import OverallState
from agent.node.node_logging import log_node_runtime


load_dotenv(override=True)

_rag_llm_model: Any | None = None

_CHAPTER_EVIDENCE_SCORE = 0.95
_CHAPTER_EVIDENCE_MAX_CHUNKS = 12
_GENERAL_EVIDENCE_LIMIT = 4
_CHAPTER_CHUNK_CHARS = 2_000


@log_node_runtime("rag_node")
def rag_node(state: OverallState) -> OverallState:
    questions = _questions_from_state(state)
    retriever = state.get("_rag_retriever") or SimpleResourceRetriever()
    package = retriever.retrieve(questions)
    chapter_context = _load_chapter_course_context(state)
    package = _with_chapter_course_evidence(state, package, chapter_context)

    llm_raw_output = ""
    if package.evidence:
        llm = state.get("_rag_llm") or _default_rag_llm()
        response = llm.invoke([_human_message(build_rag_prompt(state, package))])
        llm_raw_output = str(response.content)
        package = enrich_package_with_llm(package, llm_raw_output)

    update: OverallState = {
        "rag_package": package.model_dump(mode="json"),
        "rag_llm_raw_output": llm_raw_output,
    }
    if chapter_context:
        update["manual_lecture_content"] = str(chapter_context["manual"].get("content") or "")
        update["course_resource_bundle"] = chapter_context["bundle"]
    return update


def _with_chapter_lecture_evidence(state: OverallState, package: RagPackage) -> RagPackage:
    """Prioritize the requested chapter's curated lecture for lecture generation only."""

    if str(state.get("content_type") or "").strip().lower() != "lecture":
        return package

    return _with_chapter_course_evidence(state, package, _load_chapter_course_context(state))


def _load_chapter_course_context(state: OverallState) -> dict[str, dict[str, Any]] | None:
    content_type = str(state.get("content_type") or "").strip().lower()
    if content_type not in {"lecture", "quiz", "question", "questions"}:
        return None

    course_id = str(state.get("course_id") or "").strip()
    chapter_id = str(state.get("chapter_id") or "").strip()
    if not course_id or not chapter_id:
        return None

    try:
        repository = CourseResourceRepository(state.get("_course_resource_root"))
        bundle = repository.load_chapter_asset_bundle(course_id, chapter_id)
        manual = repository.load_manual_lecture(course_id, chapter_id)
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return None
    return {"bundle": bundle, "manual": manual}


def _with_chapter_course_evidence(
    state: OverallState,
    package: RagPackage,
    chapter_context: dict[str, dict[str, Any]] | None = None,
) -> RagPackage:
    content_type = str(state.get("content_type") or "").strip().lower()
    if content_type not in {"lecture", "quiz", "question", "questions"}:
        return package

    context = chapter_context or _load_chapter_course_context(state)
    if not context:
        return package
    bundle = context["bundle"]
    manual = context["manual"]

    chapter_evidence = _chapter_evidence_items(bundle, manual)
    if not chapter_evidence:
        return package

    chapter_ids = {item.chunk_id for item in chapter_evidence}
    general_evidence = [item for item in package.evidence if item.chunk_id not in chapter_ids]
    merged_evidence = [
        *chapter_evidence,
        *general_evidence[:_GENERAL_EVIDENCE_LIMIT],
    ]
    citations = [
        Citation(source_file=item.source_file, chunk_id=item.chunk_id, label=item.source_file)
        for item in chapter_evidence
    ]
    citation_ids = {item.chunk_id for item in citations}
    citations.extend(item for item in package.citations if item.chunk_id not in citation_ids)

    return package.model_copy(
        update={
            "evidence": merged_evidence,
            "citations": citations,
            "confidence": max(package.confidence, _CHAPTER_EVIDENCE_SCORE),
            "next_action": "use_as_grounded_context",
            "warnings": [item for item in package.warnings if item != "evidence_not_found"],
        }
    )


def _chapter_evidence_items(bundle: dict[str, Any], manual: dict[str, Any]) -> list[EvidenceItem]:
    course_id = str(bundle.get("course_id") or "").strip()
    chapter_id = str(bundle.get("chapter_id") or "").strip()
    chapter_title = str(bundle.get("title") or chapter_id).strip()
    source_path = str(manual.get("path") or "").strip()
    source_file = str(manual.get("relative_path") or Path(source_path).name or "manual_lecture.md")
    content = str(manual.get("content") or "").strip()
    if not content:
        return []

    sections = _split_chapter_markdown(content)
    evidence: list[EvidenceItem] = []
    for index, (heading, text) in enumerate(sections[:_CHAPTER_EVIDENCE_MAX_CHUNKS], start=1):
        evidence.append(
            EvidenceItem(
                source_file=source_file,
                chunk_id=f"course_resource:{course_id}:{chapter_id}:manual:{index}",
                text=text,
                score=_CHAPTER_EVIDENCE_SCORE,
                file_type="md",
                metadata={
                    "source_type": "course_resource",
                    "document_role": "chapter_manual_lecture",
                    "authoritative": True,
                    "source_path": source_path,
                    "course_id": course_id,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "section_heading": heading,
                },
            )
        )
    return evidence


def _split_chapter_markdown(content: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    heading = "章节说明"
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if not text:
            return
        for offset in range(0, len(text), _CHAPTER_CHUNK_CHARS):
            chunk = text[offset : offset + _CHAPTER_CHUNK_CHARS].strip()
            if chunk:
                blocks.append((heading, chunk))

    for line in content.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            flush()
            heading = match.group(1).strip()
            lines = [line]
        else:
            lines.append(line)
    flush()
    return blocks


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
