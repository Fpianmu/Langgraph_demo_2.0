from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.node.learning_management.profile_assessment_nodes import (
    review_profile_update_suggestions,
)
from agent.tools.profile_tools import (
    apply_profile_update_suggestions,
    load_profile_context,
)


def sync_quiz_profile_evidence(
    *,
    user_id: str,
    course_id: str,
    evidence: list[dict[str, Any]],
    request_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Persist already graded quiz evidence without asking an LLM to parse it."""

    packet = {
        "packet_id": request_id,
        "source_type": "quiz_result",
        "user_id": user_id,
        "course_id": course_id,
    }
    state = {
        "request_id": request_id,
        "user_id": user_id,
        "course_id": course_id,
        "content_type": "feedback",
    }
    gap_patches = _gap_patches(course_id, evidence)
    current = load_profile_context(user_id=user_id, storage_root=storage_root)
    gap_patches.extend(
        _superseded_legacy_quiz_gaps(
            current.get("knowledge_gaps", []),
            active_gap_ids={str(item.get("gap_id") or "") for item in gap_patches},
            incoming_evidence_ids={str(item.get("id") or "") for item in evidence},
        )
    )
    suggestions = {
        "feedback_assessment": {"feedback_type": "quiz_result"},
        "capability_evidence": evidence,
        "knowledge_gap_patches": gap_patches,
    }
    reviewed = review_profile_update_suggestions(state, packet, suggestions)
    if not reviewed.get("capability_evidence"):
        raise ValueError("no valid quiz capability evidence")
    result = apply_profile_update_suggestions(
        user_id=user_id,
        request_id=request_id,
        suggestions=reviewed,
        storage_root=storage_root,
    )
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    return {
        "status": "success",
        "user_id": user_id,
        "request_id": request_id,
        "applied_capability_evidence_count": result.get("applied_capability_evidence_count", 0),
        "applied_knowledge_gaps": result.get("applied_knowledge_gaps", []),
        "capability_assessment": context.get("capability_assessment", {}),
        "capability_profile_score": context.get("capability_profile_score", {}),
        "knowledge_gaps": context.get("knowledge_gaps", []),
    }


def _gap_patches(course_id: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_labels: dict[str, tuple[str, str]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        point_id = str(item.get("knowledgePointId") or item.get("knowledge_point_id") or "").strip()
        concept = str(item.get("knowledgePoint") or item.get("knowledge_point") or "").strip()
        if point_id or concept:
            group_id, group_concept = _canonical_gap_identity(item, point_id, concept)
            grouped[group_id].append(item)
            group_labels[group_id] = (group_id, group_concept)

    patches = []
    for point_id, items in grouped.items():
        latest = max(items, key=lambda item: str(item.get("occurredAt") or item.get("occurred_at") or ""))
        earned = sum(_number(item.get("earned")) for item in items)
        possible = sum(max(_number(item.get("possible")), 0.0001) for item in items)
        accuracy = min(max(earned / possible, 0.0), 1.0)
        point_id, concept = group_labels[point_id]
        chapter_id = _chapter_id(latest)
        dimension = str(latest.get("dimension") or "foundations")
        is_open = accuracy < 0.8 or bool(latest.get("criticalSafetyError") or latest.get("critical_safety_error"))
        evidence_items = [
            {
                "evidence_id": str(item.get("id") or ""),
                "attempt_id": str(item.get("attemptId") or item.get("attempt_id") or ""),
                "correct": bool(item.get("correct")),
                "earned": _number(item.get("earned")),
                "possible": _number(item.get("possible")),
                "question_type": str(item.get("questionType") or item.get("question_type") or ""),
                "grading_method": str(item.get("gradingMethod") or item.get("grading_method") or ""),
                "source_refs": _strings(item.get("sourceRefs") or item.get("source_refs")),
                "rag_chunk_ids": _strings(item.get("ragChunkIds") or item.get("rag_chunk_ids")),
                "occurred_at": str(item.get("occurredAt") or item.get("occurred_at") or ""),
            }
            for item in items[-12:]
        ]
        patches.append(
            {
                "gap_id": f"gap_quiz_{_safe_id(course_id)}_{_safe_id(point_id)}",
                "knowledge_point_id": point_id,
                "concept": concept,
                "chapter_id": chapter_id,
                "category": dimension,
                "severity": "high" if dimension == "safety" and is_open else "medium" if is_open else "low",
                "score": accuracy,
                "evidence": f"Quiz 共 {len(items)} 条有效证据，得分率 {round(accuracy * 100)}%。",
                "evidence_items": evidence_items,
                "status": "open" if is_open else "resolved",
                "source": "quiz_result",
                "recommended_actions": (
                    [f"复习 Chapter {chapter_id} 中“{concept}”并完成针对性练习。"]
                    if is_open
                    else [f"“{concept}”当前已达到掌握标准，后续定期复测。"]
                ),
            }
        )
    return patches


def _chapter_id(item: dict[str, Any]) -> str:
    explicit = str(item.get("chapterId") or item.get("chapter_id") or "").strip()
    if re.fullmatch(r"[1-5](?:\.\d+)?", explicit):
        return explicit
    point_id = str(item.get("knowledgePointId") or item.get("knowledge_point_id") or "")
    match = re.search(r"(?:^|\.)([1-5]\.\d+)(?:\.|$)", point_id)
    if match:
        return match.group(1)
    return {
        "foundations": "1.1",
        "safety": "2.1",
        "machining_operation": "3.1",
        "programming": "4.1",
        "process_planning": "4.2",
        "quality_control": "5.1",
        "maintenance": "5.2",
        "advanced_manufacturing": "5.3",
    }.get(str(item.get("dimension") or ""), "1.1")


def _safe_id(value: str) -> str:
    raw = str(value).strip()
    token = re.sub(r"[^0-9A-Za-z_.-]+", "_", raw).strip("_")[:48]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{token or 'kp'}_{digest}"


def _superseded_legacy_quiz_gaps(
    gaps: Any,
    *,
    active_gap_ids: set[str],
    incoming_evidence_ids: set[str],
) -> list[dict[str, Any]]:
    patches = []
    if not isinstance(gaps, list):
        return patches
    for gap in gaps:
        if not isinstance(gap, dict) or str(gap.get("source") or "") != "quiz_result":
            continue
        gap_id = str(gap.get("gap_id") or "")
        if gap_id in active_gap_ids:
            continue
        gap_evidence_ids = {
            str(item.get("evidence_id") or "")
            for item in _evidence_items(gap)
            if isinstance(item, dict)
        }
        is_old_id = not re.search(r"_[0-9a-f]{12}$", gap_id)
        replaced_by_current_sync = bool(gap_evidence_ids & incoming_evidence_ids)
        if not is_old_id and not replaced_by_current_sync:
            continue
        patches.append(
            {
                "gap_id": gap_id,
                "knowledge_point_id": str(gap.get("knowledge_point_id") or ""),
                "concept": str(gap.get("concept") or "旧版 Quiz 漏洞记录"),
                "chapter_id": str(gap.get("chapter_id") or "1.1"),
                "category": str(gap.get("category") or "foundations"),
                "severity": "low",
                "score": _number(gap.get("score")),
                "evidence": "该记录由旧版中文 ID 规则产生，已由无碰撞的新版记录替代。",
                "evidence_items": [],
                "status": "resolved",
                "source": "quiz_result",
                "recommended_actions": [],
            }
        )
    return patches


def _canonical_gap_identity(
    item: dict[str, Any],
    point_id: str,
    concept: str,
) -> tuple[str, str]:
    """Collapse legacy question-stem records into actual conceptual gaps.

    Older frontend sessions used the complete question stem as the knowledge
    point.  Showing one gap per missed question makes the user center noisy and
    misrepresents a knowledge gap.  Structured IDs from current sessions remain
    untouched; only question-like legacy values are grouped by chapter, topic
    and capability dimension while their individual evidence stays attached.
    """

    topic = str(item.get("topic") or "").strip()
    dimension = str(item.get("dimension") or "foundations").strip()
    chapter_id = _chapter_id(item)
    if topic and _looks_like_question_stem(point_id, concept):
        identity = f"{chapter_id}:{dimension}:{topic}"
        return identity, f"{topic} · {_dimension_label(dimension)}"
    return point_id or _safe_id(concept), concept or point_id


def _looks_like_question_stem(point_id: str, concept: str) -> bool:
    text = concept or point_id
    if any(marker in text for marker in ("？", "?", "下列", "是否", "说明", "哪些", "是什么", "____")):
        return True
    compact = re.sub(r"\s+", "", text)
    structured = bool(re.search(r"[.:/]", point_id))
    return len(compact) >= 26 and not structured


def _dimension_label(dimension: str) -> str:
    return {
        "safety": "安全规范",
        "foundations": "专业基础",
        "process_planning": "工艺规划",
        "programming": "数控编程",
        "machining_operation": "操作加工",
        "quality_control": "质量检测",
        "maintenance": "维护诊断",
        "advanced_manufacturing": "先进制造",
    }.get(dimension, "综合能力")


def _evidence_items(gap: dict[str, Any]) -> list[Any]:
    value = gap.get("evidence_items") or gap.get("evidence_items_json") or []
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
