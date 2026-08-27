from __future__ import annotations

import logging
import re
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.profile.capability_assessment_store import CAPABILITY_DIMENSION_IDS
from agent.tools.learning_recommendation_tools import refresh_learning_recommendations
from agent.tools.profile_tools import apply_profile_update_suggestions


LOGGER = logging.getLogger("agent.profile_assessment")

_SOURCE_TYPES = {"quiz", "practice", "external_assessment"}
_DIFFICULTIES = {"easy", "medium", "hard"}
_REVIEW_STATUSES = {"auto_verified", "pending_review", "reviewed", "rejected"}


@log_node_runtime("profile_assessment_review_node")
def profile_assessment_review_node(state: OverallState) -> OverallState:
    packet = state.get("profile_evidence_packet") if isinstance(state.get("profile_evidence_packet"), dict) else {}
    suggestions = packet.get("proposed_profile_changes") if isinstance(packet.get("proposed_profile_changes"), dict) else {}
    if not suggestions and isinstance(state.get("profile_update_suggestions"), dict):
        suggestions = state.get("profile_update_suggestions") or {}
    if not suggestions and isinstance(state.get("operation_profile_update_suggestions"), dict):
        suggestions = state.get("operation_profile_update_suggestions") or {}
    reviewed = _reviewed_suggestions(state, packet, suggestions)
    approved = _has_any_profile_change(reviewed)
    result = {
        "approved": approved,
        "source_packet_id": str(packet.get("packet_id") or state.get("request_id") or ""),
        "source_type": str(
            packet.get("source_type")
            or (suggestions.get("feedback_assessment") or {}).get("feedback_type")
            or ""
        ),
        "review_status": "approved" if approved else "no_valid_profile_changes",
        "applied_policy": "normalize_feedback_evidence_before_profile_write",
        "dropped_capability_evidence": max(
            0,
            len(suggestions.get("capability_evidence") or []) - len(reviewed.get("capability_evidence") or []),
        ),
    }
    LOGGER.info(
        "profile_assessment_review_node reviewed packet user_id=%s packet_id=%s approved=%s "
        "capability_evidence=%d knowledge_gap_patches=%d",
        str(state.get("user_id") or packet.get("user_id") or "default_user"),
        str(packet.get("packet_id") or ""),
        approved,
        len(reviewed.get("capability_evidence") or []),
        len(reviewed.get("knowledge_gap_patches") or []),
    )
    return {
        "profile_assessment_review_result": result,
        "profile_update_suggestions": reviewed,
    }


@log_node_runtime("profile_assessment_apply_node")
def profile_assessment_apply_node(state: OverallState) -> OverallState:
    review = state.get("profile_assessment_review_result") if isinstance(state.get("profile_assessment_review_result"), dict) else {}
    suggestions = state.get("profile_update_suggestions") if isinstance(state.get("profile_update_suggestions"), dict) else {}
    if not review.get("approved") or not _has_any_profile_change(suggestions):
        return {
            "profile_update_result": {"accepted": False, "reason": "profile_assessment_review_not_approved"},
            "feedback_result": {
                "status": "no_update",
                "feedback_type": str((state.get("feedback_assessment") or {}).get("feedback_type") or ""),
                "message": "画像证据包未通过中间层审核，未写入 profile。",
            },
        }

    update_result = apply_profile_update_suggestions(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or review.get("source_packet_id") or ""),
        suggestions=suggestions,
        storage_root=state.get("_storage_root"),
    )
    recommendation_refresh_result = _refresh_recommendations_after_profile_update(state)
    LOGGER.info(
        "profile_assessment_apply_node applied profile update user_id=%s request_id=%s accepted=%s event_id=%s "
        "applied_metrics=%d applied_capability_evidence=%d applied_knowledge_gaps=%d applied_learning_progress=%d",
        str(state.get("user_id") or "default_user"),
        str(state.get("request_id") or review.get("source_packet_id") or ""),
        bool(update_result.get("accepted")),
        str(update_result.get("event_id") or ""),
        len(update_result.get("applied_metrics") or []),
        len(update_result.get("applied_capability_evidence") or []),
        len(update_result.get("applied_knowledge_gaps") or []),
        len(update_result.get("applied_learning_progress") or []),
    )
    update_result["learning_recommendation_refresh"] = recommendation_refresh_result
    return {
        "profile_update_result": update_result,
        "learning_recommendations": recommendation_refresh_result.get("recommendations") if recommendation_refresh_result.get("status") == "success" else {},
        "learning_recommendation_refresh_result": recommendation_refresh_result,
        "feedback_result": {
            "status": "success",
            "feedback_type": str((state.get("feedback_assessment") or {}).get("feedback_type") or ""),
            "message": "已通过学情画像中间层审核并更新用户画像。",
            "applied_metrics": len(update_result.get("applied_metrics") or []),
            "applied_capability_evidence": len(update_result.get("applied_capability_evidence") or []),
            "applied_knowledge_gaps": len(update_result.get("applied_knowledge_gaps") or []),
            "applied_learning_progress": len(update_result.get("applied_learning_progress") or []),
        },
    }


def _refresh_recommendations_after_profile_update(state: OverallState) -> dict[str, Any]:
    try:
        return refresh_learning_recommendations(
            user_id=str(state.get("user_id") or "default_user"),
            storage_root=state.get("_storage_root"),
        )
    except Exception as exc:
        LOGGER.warning("learning recommendation refresh failed after profile update: %s", exc)
        return {"status": "failed", "reason": str(exc)}


def _reviewed_suggestions(
    state: OverallState,
    packet: dict[str, Any],
    suggestions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_node": "profile_assessment_review_node",
        "source_packet_id": str(packet.get("packet_id") or ""),
        "feedback_assessment": suggestions.get("feedback_assessment") if isinstance(suggestions.get("feedback_assessment"), dict) else {},
        "metric_patches": _list_of_dicts(suggestions.get("metric_patches")),
        "capability_evidence": _normalize_capability_evidence(state, packet, suggestions.get("capability_evidence")),
        "knowledge_gap_patches": _normalize_gap_patches(suggestions.get("knowledge_gap_patches")),
        "progress_patches": _list_of_dicts(suggestions.get("progress_patches")),
        **_markdown_patch(suggestions.get("markdown_patch")),
    }


def _normalize_capability_evidence(state: OverallState, packet: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    packet_id = str(packet.get("packet_id") or state.get("request_id") or "feedback")
    for index, candidate in enumerate(value, start=1):
        if not isinstance(candidate, dict):
            continue
        dimension = _dimension(candidate.get("dimension"))
        knowledge_point = str(
            candidate.get("knowledgePoint")
            or candidate.get("knowledge_point")
            or candidate.get("knowledge_point_name")
            or candidate.get("topic")
            or ""
        ).strip()
        if not dimension or not knowledge_point:
            continue
        evidence_id = str(candidate.get("id") or "").strip() or f"{packet_id}-{index}-{dimension}-{_safe_id(knowledge_point)}"
        possible = _positive_float(candidate.get("possible"), 1.0)
        earned = min(max(_float(candidate.get("earned"), 0.0), 0.0), possible)
        return_item = {
            **candidate,
            "id": evidence_id,
            "attemptId": str(candidate.get("attemptId") or candidate.get("attempt_id") or packet.get("attempt_id") or packet_id),
            "sourceType": _choice(candidate.get("sourceType") or candidate.get("source_type"), _SOURCE_TYPES, "external_assessment"),
            "dimension": dimension,
            "topic": str(candidate.get("topic") or knowledge_point).strip(),
            "knowledgePoint": knowledge_point,
            "correct": bool(candidate.get("correct")),
            "earned": earned,
            "possible": possible,
            "difficulty": _choice(candidate.get("difficulty"), _DIFFICULTIES, "medium"),
            "knowledgePointId": str(
                candidate.get("knowledgePointId")
                or candidate.get("knowledge_point_id")
                or _safe_id(knowledge_point)
            ),
            "dimensionSource": str(candidate.get("dimensionSource") or candidate.get("dimension_source") or "declared"),
            "questionGrounded": bool(candidate.get("questionGrounded", candidate.get("question_grounded", False))),
            "reviewStatus": _choice(
                candidate.get("reviewStatus") or candidate.get("review_status"),
                _REVIEW_STATUSES,
                "pending_review",
            ),
            "chapterId": str(candidate.get("chapterId") or candidate.get("chapter_id") or packet.get("chapter_id") or state.get("chapter_id") or ""),
        }
        result.append(return_item)
    return result


def _normalize_gap_patches(value: Any) -> list[dict[str, Any]]:
    patches = []
    for item in _list_of_dicts(value):
        concept = str(item.get("concept") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if concept and evidence:
            patches.append(item)
    return patches


def _markdown_patch(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    section = str(value.get("section") or "").strip()
    content = str(value.get("content") or "").strip()
    return {"markdown_patch": {"section": section, "content": content}} if section and content else {}


def _has_any_profile_change(suggestions: dict[str, Any]) -> bool:
    return bool(
        suggestions.get("metric_patches")
        or suggestions.get("capability_evidence")
        or suggestions.get("knowledge_gap_patches")
        or suggestions.get("progress_patches")
        or suggestions.get("markdown_patch")
    )


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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _positive_float(value: Any, default: float) -> float:
    return max(_float(value, default), 0.0001)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_id(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value).strip()).strip("_")
    return token or "knowledge_point"
