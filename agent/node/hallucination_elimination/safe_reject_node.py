from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.hallucination_elimination.verified_persistence_node import verified_persistence_node
from agent.node.verification_utils import get_review_materials, write_review_materials
from agent.state import OverallState


@log_node_runtime("safe_reject_node")
def safe_reject_node(state: OverallState) -> OverallState:
    materials = get_review_materials(state)
    rejected = {kind: _reject_material(state, kind, material) for kind, material in materials.items()}
    update = write_review_materials(state, rejected)
    if len(rejected) == 1 and "single" in rejected:
        update["verified_output"] = rejected["single"]
    else:
        update["verified_materials"] = rejected
    grounded = bool(rejected) and all(_is_grounded_fallback(item) for item in rejected.values())
    update["verification_decision"] = "grounded_fallback" if grounded else "safe_reject_node"
    if grounded:
        persisted = verified_persistence_node({**state, **update})
        update.update(persisted)
    return update


def _reject_material(state: OverallState, kind: str, material: dict) -> dict:
    result = deepcopy(material)
    meta = result.setdefault("meta", {})
    content_type = str(meta.get("content_type") or kind) if isinstance(meta, dict) else kind

    if content_type == "lecture" and _apply_grounded_lecture_fallback(state, result):
        return result
    if content_type in {"quiz", "question", "questions"} and _apply_grounded_quiz_fallback(state, result):
        return result

    # QA is allowed to return a deliberately bounded conclusion when retrieval
    # found usable evidence.  The verifier may still reject some generated
    # claims after its retrieval/rewrite budget is exhausted; replacing the
    # entire answer with a generic refusal would also discard the grounded RAG
    # conclusion.  Keep the verifier's strict decision, but expose only the
    # retriever's evidence-scoped answer and its explicit knowledge boundary.
    if content_type in {"qa", "qa_answer"} and _apply_bounded_rag_answer(state, result):
        if isinstance(meta, dict):
            meta["status"] = "partial"
            meta["verification_status"] = "bounded"
        result["summary"] = "已依据当前知识库给出可确认的范围，并标明资料不足之处。"
        return result

    if isinstance(meta, dict):
        meta["status"] = "rejected"
        meta["verification_status"] = "rejected"
    result["summary"] = "当前知识库证据不足，暂不输出确定性结论。"
    if content_type == "lecture":
        result["payload"] = {"sections": [{"heading": "证据状态", "content": "当前知识库不足以可靠生成该部分内容。"}]}
    elif content_type in {"practice", "practice_guide"}:
        result["payload"] = {
            "objectives": [],
            "steps": ["需补充资料后再执行。"],
            "checklist": [],
            "safety_points": ["不得基于未验证信息执行操作。"],
        }
    elif content_type in {"quiz", "question", "questions"}:
        result["payload"] = {"questions": []}
    elif content_type in {"qa", "qa_answer"}:
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        payload["answer"] = "当前知识库未提供足够依据，暂不提供确定性结论。"
        result["payload"] = payload
    return result


def _is_grounded_fallback(material: dict[str, Any]) -> bool:
    meta = material.get("meta")
    return isinstance(meta, dict) and meta.get("verification_status") == "grounded_fallback"


def _apply_grounded_lecture_fallback(state: OverallState, result: dict[str, Any]) -> bool:
    content = str(state.get("manual_lecture_content") or "").strip()
    if not content:
        return False
    sections = _markdown_sections(content)
    if not sections:
        return False
    meta = result.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["status"] = "success"
        meta["verification_status"] = "grounded_fallback"
        meta["source"] = "chapter_manual_lecture"
    result["summary"] = "个性化内容未完全通过核验，已回退为当前章节的权威标准讲义。"
    result["payload"] = {"sections": sections}
    result["evidence_refs"] = _course_evidence_refs(state)
    return True


def _markdown_sections(content: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    heading = "章节正文"
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append({"heading": heading, "content": text})

    for line in content.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            flush()
            heading = match.group(1).strip()
            body = []
        else:
            body.append(line)
    flush()
    return sections[:24]


def _apply_grounded_quiz_fallback(state: OverallState, result: dict[str, Any]) -> bool:
    reference_quiz = state.get("reference_quiz")
    references = reference_quiz.get("questions") if isinstance(reference_quiz, dict) else []
    references = [item for item in references if isinstance(item, dict)] if isinstance(references, list) else []
    slots = state.get("quiz_blueprint_slots")
    slots = [item for item in slots if isinstance(item, dict)] if isinstance(slots, list) else []
    if not references or not slots:
        return False

    questions = [
        _question_from_reference(state, references[index % len(references)], slot, index)
        for index, slot in enumerate(slots)
    ]
    if not questions:
        return False
    meta = result.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["status"] = "success"
        meta["verification_status"] = "grounded_fallback"
        meta["source"] = "chapter_reference_quiz"
    result["summary"] = "生成题未完全通过核验，已使用当前章节权威参考题重新构造本批测验。"
    result["payload"] = {"questions": questions}
    result["evidence_refs"] = [
        {"source_doc": "reference_quiz", "chunk_id": f"reference_quiz_{index + 1:04d}"}
        for index in range(len(questions))
    ]
    return True


def _question_from_reference(
    state: OverallState,
    source: dict[str, Any],
    slot: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    sequence = _int_value(slot.get("sequence"), index + 1)
    question_type = str(slot.get("question_type") or "short_answer")
    source_stem = str(source.get("stem") or "请概括本节核心知识。 ").strip()
    source_answer = str(source.get("reference_answer") or source.get("answer") or "").strip()
    explanation = str(source.get("explanation") or source_answer).strip()
    source_id = str(source.get("question_id") or f"reference_{index + 1:04d}")
    common: dict[str, Any] = {
        "question_id": f"grounded_{state.get('chapter_id')}_{sequence:03d}".replace(".", "_"),
        "sequence": sequence,
        "question_type": question_type,
        "difficulty": str(slot.get("difficulty") or source.get("difficulty") or "normal"),
        "points": slot.get("points"),
        "capability_dimension": str(slot.get("capability_dimension") or "foundations"),
        "question_purpose": str(slot.get("question_purpose") or "chapter_core"),
        "related_gap_ids": slot.get("related_gap_ids") if isinstance(slot.get("related_gap_ids"), list) else [],
        "knowledge_points": source.get("knowledge_points") if isinstance(source.get("knowledge_points"), list) else [],
        "core_exam_points": source.get("core_exam_points") if isinstance(source.get("core_exam_points"), list) else [],
        "concise_explanation": explanation,
        "detailed_explanation": explanation,
        "explanation": explanation,
        "source_refs": [f"reference_quiz:{source_id}"],
    }
    if question_type == "single_choice":
        common.update(
            {
                "stem": f"根据本章标准资料，关于“{source_stem}”的正确回答是？",
                "options": [
                    source_answer,
                    "该内容不属于本章学习范围",
                    "仅凭个人经验判断即可",
                    "标准资料没有给出任何相关说明",
                ],
                "answer": "A",
                "reference_answer": "A",
            }
        )
    elif question_type == "true_false":
        common.update(
            {
                "stem": f"根据本章标准资料，以下结论正确：{source_answer}",
                "options": ["正确", "错误"],
                "answer": "A",
                "reference_answer": "正确",
            }
        )
    elif question_type == "cloze":
        common.update(
            {
                "stem": f"请根据本章标准资料填写：{source_stem}",
                "options": [],
                "answer": source_answer,
                "reference_answer": source_answer,
            }
        )
    else:
        common.update(
            {
                "stem": source_stem,
                "options": [],
                "answer": source_answer,
                "reference_answer": source_answer,
                "scoring_rubric": {
                    "key_points": [{"description": source_answer, "points": slot.get("points") or 5}]
                },
            }
        )
    return common


def _course_evidence_refs(state: OverallState) -> list[dict[str, str]]:
    package = state.get("rag_package")
    evidence = package.get("evidence") if isinstance(package, dict) else []
    refs = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("source_type") != "course_resource":
            continue
        refs.append(
            {
                "source_doc": str(item.get("source_file") or "chapter_manual_lecture"),
                "chunk_id": str(item.get("chunk_id") or ""),
            }
        )
    return refs


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _apply_bounded_rag_answer(state: OverallState, result: dict) -> bool:
    package = state.get("rag_package")
    if not isinstance(package, dict):
        return False

    grounded_answer = _humanize_evidence_wording(str(package.get("answer") or "").strip())
    evidence = package.get("evidence")
    if not grounded_answer or not isinstance(evidence, list) or not any(isinstance(item, dict) for item in evidence):
        return False

    # Keep the first-version chat presentation: one coherent assistant answer.
    # RAG evidence and verification metadata remain in the state/result, but are
    # not exposed as two artificial answer sections in the conversation UI.
    original_answer = _original_qa_answer(state)
    answer = original_answer or grounded_answer

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    payload["answer"] = answer
    result["payload"] = payload

    warnings = package.get("warnings")
    if isinstance(warnings, list):
        boundaries = [str(item).strip() for item in warnings if str(item).strip()]
        if boundaries:
            existing = result.get("safety_notes")
            notes = list(existing) if isinstance(existing, list) else []
            result["safety_notes"] = list(dict.fromkeys([*notes, *boundaries]))
    return True


def _original_qa_answer(state: OverallState) -> str:
    material = state.get("final_qa_output")
    if not isinstance(material, dict):
        return ""
    payload = material.get("payload")
    if not isinstance(payload, dict):
        return ""
    return _humanize_evidence_wording(str(payload.get("answer") or "").strip())


def _humanize_evidence_wording(text: str) -> str:
    return (
        text.replace("根据提供的证据", "根据当前知识库证据")
        .replace("提供的evidence", "当前知识库证据")
        .replace("提供的 evidence", "当前知识库证据")
        .replace("在evidence中", "在知识库证据中")
        .replace("在 evidence 中", "在知识库证据中")
    )
