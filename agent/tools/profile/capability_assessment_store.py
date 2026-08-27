from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.profile.capability_assessment_calculator import (
    ASSESSMENT_MODEL_VERSION,
    CAPABILITY_DIMENSION_IDS,
    assessment_to_score_map,
    calculate_capability_assessment,
)
from agent.tools.profile.capability_profile_score import build_capability_profile_score
from agent.tools.profile.repository import ProfileRepository


DIFFICULTIES = {"easy", "medium", "hard"}
DIMENSION_SOURCES = {"declared", "keyword", "fallback"}
REVIEW_STATUSES = {"auto_verified", "pending_review", "reviewed", "rejected"}
SOURCE_TYPES = {"quiz", "practice", "external_assessment"}


class CapabilityAssessmentDbStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.repository = ProfileRepository(self.db_path)

    def sync(self, user_id: str) -> dict[str, Any]:
        self.repository.get_or_create_user(user_id)
        document = self.load(user_id)
        self.repository.set_capability_assessment(user_id, document)
        profile_score = build_capability_profile_score(document)
        self.repository.set_capability_profile_score(user_id, profile_score)
        return {
            "document": document,
            "profile_score": profile_score,
            "files": self.file_refs_for(user_id),
            "summary": _summary_for(document.get("evidence") or []),
        }

    def append_evidence(self, user_id: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        current = self.load(user_id)
        merged = _merge_evidence(
            current.get("evidence") if isinstance(current.get("evidence"), list) else [],
            evidence,
        )
        document = _document_for(merged)
        self.repository.set_capability_assessment(user_id, document)
        profile_score = build_capability_profile_score(document)
        self.repository.set_capability_profile_score(user_id, profile_score)
        applied_ids = {item["id"] for item in _normalize_evidence_list(evidence)}
        applied = [item for item in merged if item.get("id") in applied_ids]
        return {
            "document": document,
            "profile_score": profile_score,
            "applied_evidence": applied,
            "files": self.file_refs_for(user_id),
            "summary": _summary_for(document["evidence"]),
        }

    def load(self, user_id: str) -> dict[str, Any]:
        value = self.repository.get_capability_assessment(user_id)
        if not isinstance(value, dict):
            return _document_for([])
        return _document_for(_normalize_evidence_list(value.get("evidence")))

    def file_refs_for(self, user_id: str) -> dict[str, str]:
        return {"db": str(self.db_path)}


def _document_for(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    assessment = calculate_capability_assessment(evidence)
    score_map = assessment_to_score_map(assessment)
    summary = _summary_for(evidence)
    return {
        "model_version": ASSESSMENT_MODEL_VERSION,
        "policy_version": "scoring-policy-v2",
        "updated_at": _now(),
        "summary": summary,
        "assessment": assessment,
        "score_map": score_map,
        "evidence": evidence,
    }


def _merge_evidence(current: list[Any], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in _normalize_evidence_list(incoming) + _normalize_evidence_list(current):
        if item["id"] not in by_id:
            by_id[item["id"]] = item
    return sorted(by_id.values(), key=lambda item: str(item.get("occurredAt") or ""), reverse=True)[:2000]


def _normalize_evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for candidate in value:
        if not isinstance(candidate, dict):
            continue
        item = _normalize_evidence(candidate)
        if item:
            result.append(item)
    return result


def _normalize_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    evidence_id = str(item.get("id") or "").strip()
    attempt_id = str(item.get("attemptId") or item.get("attempt_id") or "").strip()
    dimension = _dimension(item.get("dimension"))
    knowledge_point = str(item.get("knowledgePoint") or item.get("knowledge_point") or "").strip()
    if not evidence_id or not attempt_id or not dimension or not knowledge_point:
        return None
    possible = _positive_float(item.get("possible"), default=1.0)
    earned = min(max(_float(item.get("earned"), default=0.0), 0.0), possible)
    occurred_at = str(item.get("occurredAt") or item.get("occurred_at") or "").strip() or _now()
    return {
        "id": evidence_id,
        "attemptId": attempt_id,
        "sourceType": _choice(item.get("sourceType") or item.get("source_type"), SOURCE_TYPES, "quiz"),
        "dimension": dimension,
        "topic": str(item.get("topic") or "").strip(),
        "knowledgePoint": knowledge_point,
        "correct": bool(item.get("correct")),
        "earned": earned,
        "possible": possible,
        "difficulty": _choice(item.get("difficulty"), DIFFICULTIES, "easy"),
        "occurredAt": occurred_at,
        "sourceRefs": _string_list(item.get("sourceRefs") or item.get("source_refs")),
        "ragChunkIds": _string_list(item.get("ragChunkIds") or item.get("rag_chunk_ids")),
        "questionType": str(item.get("questionType") or item.get("question_type") or "").strip() or None,
        "gradingMethod": str(item.get("gradingMethod") or item.get("grading_method") or "").strip() or None,
        "rubricVersion": str(item.get("rubricVersion") or item.get("rubric_version") or "").strip() or None,
        "semanticScore": _optional_unit(item.get("semanticScore") or item.get("semantic_score")),
        "keyPointScore": _optional_unit(item.get("keyPointScore") or item.get("key_point_score")),
        "graderConfidence": _optional_unit(item.get("graderConfidence") or item.get("grader_confidence")),
        "keyPointCoverage": _dict_or_none(item.get("keyPointCoverage") or item.get("key_point_coverage")),
        "gradingResult": _dict_or_none(item.get("gradingResult") or item.get("grading_result")),
        "coreExamPoints": _string_list(item.get("coreExamPoints") or item.get("core_exam_points")),
        "attemptNumber": max(1, int(_float(item.get("attemptNumber") or item.get("attempt_number"), default=1))),
        "itemRevision": str(item.get("itemRevision") or item.get("item_revision") or evidence_id).strip(),
        "knowledgePointId": str(
            item.get("knowledgePointId") or item.get("knowledge_point_id") or _knowledge_point_id(knowledge_point)
        ).strip(),
        "dimensionSource": _choice(
            item.get("dimensionSource") or item.get("dimension_source"),
            DIMENSION_SOURCES,
            "fallback",
        ),
        "questionGrounded": bool(item.get("questionGrounded", item.get("question_grounded", False))),
        "reviewStatus": _choice(item.get("reviewStatus") or item.get("review_status"), REVIEW_STATUSES, "auto_verified"),
        "reviewedBy": str(item.get("reviewedBy") or item.get("reviewed_by") or "").strip() or None,
        "lectureId": str(item.get("lectureId") or item.get("lecture_id") or "").strip() or None,
        "chapterId": str(item.get("chapterId") or item.get("chapter_id") or "").strip() or None,
        "objectiveIds": _string_list(item.get("objectiveIds") or item.get("objective_ids")),
        "criticalSafetyError": bool(item.get("criticalSafetyError") or item.get("critical_safety_error")),
    }


def _summary_for(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    assessment = calculate_capability_assessment(evidence)
    score_map = assessment_to_score_map(assessment)
    by_dimension = {dimension: 0 for dimension in sorted(CAPABILITY_DIMENSION_IDS)}
    earned_by_dimension = {dimension: 0.0 for dimension in sorted(CAPABILITY_DIMENSION_IDS)}
    possible_by_dimension = {dimension: 0.0 for dimension in sorted(CAPABILITY_DIMENSION_IDS)}
    for item in evidence:
        dimension = str(item.get("dimension") or "")
        if dimension in by_dimension:
            by_dimension[dimension] += 1
            possible = _positive_float(item.get("possible"), default=1.0)
            earned_by_dimension[dimension] += min(max(_float(item.get("earned"), default=0.0), 0.0), possible)
            possible_by_dimension[dimension] += possible
    dimension_scores = {
        dimension: _dimension_score(earned_by_dimension[dimension], possible_by_dimension[dimension])
        for dimension in sorted(CAPABILITY_DIMENSION_IDS)
    }
    overall_score = _dimension_score(sum(earned_by_dimension.values()), sum(possible_by_dimension.values()))
    return {
        "evidence_count": len(evidence),
        "effective_evidence_count": assessment["effectiveEvidenceCount"],
        "assessed_dimension_count": assessment["assessedDimensionCount"],
        "rated_dimension_count": assessment["ratedDimensionCount"],
        "by_dimension": by_dimension,
        "dimension_scores": dimension_scores,
        "overall_score": overall_score,
        "formal_dimension_scores": {
            dimension: (assessment["dimensions"][dimension]["score"] if assessment["dimensions"][dimension]["ratingReady"] else 0)
            for dimension in sorted(CAPABILITY_DIMENSION_IDS)
        },
        "formal_overall_score": score_map["overall"],
        "provisional_overall_score": score_map["provisional_overall"],
        "assessment_confidence": score_map["assessment_confidence"],
    }


def _dimension(value: Any) -> str:
    token = str(value or "").strip()
    aliases = {
        "theory": "foundations",
        "基础理论": "foundations",
        "基础识图": "foundations",
        "operation": "machining_operation",
        "操作加工": "machining_operation",
        "工艺规划": "process_planning",
        "工艺分析": "process_planning",
        "数控编程": "programming",
        "质量检测": "quality_control",
        "维护诊断": "maintenance",
        "先进制造": "advanced_manufacturing",
        "安全": "safety",
    }
    normalized = token.lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in CAPABILITY_DIMENSION_IDS else aliases.get(token, "")


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_unit(value: Any) -> float | None:
    if value is None:
        return None
    return min(max(_float(value, default=0.0), 0.0), 1.0)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _positive_float(value: Any, *, default: float) -> float:
    return max(_float(value, default=default), 0.0001)


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_score(value: Any) -> float:
    return min(max(_float(value, default=0.0), 0.0), 1.0)


def _dimension_score(earned: float, possible: float) -> float:
    if possible <= 0:
        return 0.0
    return round(min(max(100.0 * earned / possible, 0.0), 100.0), 2)


def _knowledge_point_id(value: str) -> str:
    token = "".join(char.lower() for char in str(value).strip() if char.isalnum())
    return token or "knowledge_point"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
