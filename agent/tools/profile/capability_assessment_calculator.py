from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.tools.profile.capability_scoring_policy import (
    CAPABILITY_RATING_POLICY,
    CNC_JOB_CAPABILITY_WEIGHTS,
    DIFFICULTY_WEIGHT,
    DIMENSION_SOURCE_RELIABILITY,
    SOURCE_RELIABILITY,
)


ASSESSMENT_MODEL_VERSION = "cnc-capability-v2"

CAPABILITY_DIMENSIONS: list[dict[str, Any]] = [
    {
        "id": "safety",
        "label": "安全规范与职业素养",
        "shortLabel": "安全规范",
        "description": "个人防护、开机检查、急停、异常处置、电气安全与 6S 规范",
        "evidenceHint": "安全题库、情境判断和规范操作题",
    },
    {
        "id": "foundations",
        "label": "专业基础与识图",
        "shortLabel": "基础识图",
        "description": "机床原理、坐标系、机械制图、公差、材料与切削基础",
        "evidenceHint": "理论题、图纸识读题和概念辨析题",
    },
    {
        "id": "process_planning",
        "label": "工艺分析与加工规划",
        "shortLabel": "工艺规划",
        "description": "工艺路线、工序安排、刀夹量具选择、装夹方案与切削参数",
        "evidenceHint": "工艺案例、工艺卡和方案选择题",
    },
    {
        "id": "programming",
        "label": "数控编程与程序校验",
        "shortLabel": "数控编程",
        "description": "G/M 指令、循环、刀补、手工编程、CAM、仿真与程序校验",
        "evidenceHint": "编程题、程序纠错题和仿真校验题",
    },
    {
        "id": "machining_operation",
        "label": "机床操作与加工实施",
        "shortLabel": "操作加工",
        "description": "回零、对刀、装夹、试运行、自动加工与现场参数调整",
        "evidenceHint": "操作流程题、模拟实训和实际操作记录",
    },
    {
        "id": "quality_control",
        "label": "质量检测与误差控制",
        "shortLabel": "质量检测",
        "description": "量具使用、尺寸和形位公差、表面质量、误差分析与补偿",
        "evidenceHint": "检测题、测量结果和加工质量数据",
    },
    {
        "id": "maintenance",
        "label": "设备维护与故障处理",
        "shortLabel": "维护诊断",
        "description": "清洁润滑、日常保养、报警识别和机械电气液压故障处理",
        "evidenceHint": "报警诊断、故障案例和维护任务",
    },
    {
        "id": "advanced_manufacturing",
        "label": "先进加工与智能制造",
        "shortLabel": "先进制造",
        "description": "车铣复合、多轴加工、后处理、远程运维与智能制造应用",
        "evidenceHint": "中高级综合题、多轴任务和智能制造案例",
    },
]

CAPABILITY_DIMENSION_IDS = {item["id"] for item in CAPABILITY_DIMENSIONS}


def calculate_capability_assessment(evidence: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    accepted = [item for item in evidence if _valid_evidence(item)]
    effective = effective_capability_evidence(accepted)
    dimensions = {}
    for definition in CAPABILITY_DIMENSIONS:
        dimension_id = str(definition["id"])
        raw_items = [item for item in accepted if item.get("dimension") == dimension_id]
        items = [item for item in effective if item.get("dimension") == dimension_id]
        overall = _calculate_score_slice(items, current_time)
        knowledge_items = [
            item for item in items if item.get("sourceType") in {"quiz", "external_assessment"}
        ]
        practice_items = [
            item for item in items if item.get("sourceType") in {"practice", "external_assessment"}
        ]
        knowledge = _calculate_score_slice(knowledge_items, current_time)
        practice = _calculate_score_slice(practice_items, current_time)
        dimensions[dimension_id] = {
            **definition,
            "score": overall["score"],
            "observedScore": overall["observedScore"],
            "weightedAccuracy": overall["weightedAccuracy"],
            "evidenceCount": len(raw_items),
            "effectiveEvidenceCount": len(items),
            "knowledgePointCount": overall["knowledgePointCount"],
            "independentAttemptCount": overall["independentAttemptCount"],
            "effectiveWeight": overall["effectiveWeight"],
            "confidence": overall["confidence"],
            "confidenceLabel": _confidence_label(len(items), overall["confidence"]),
            "masteryLabel": _mastery_label(overall["score"], overall["status"]),
            "ratingStatus": overall["status"],
            "ratingReady": overall["status"] == "rated",
            "knowledgeScore": knowledge["score"],
            "knowledgeObservedScore": knowledge["observedScore"],
            "knowledgeStatus": knowledge["status"],
            "knowledgeEvidenceCount": len(knowledge_items),
            "practiceScore": practice["score"],
            "practiceObservedScore": practice["observedScore"],
            "practiceStatus": practice["status"],
            "practiceEvidenceCount": len([item for item in practice_items if item.get("sourceType") == "practice"]),
            "externalEvidenceCount": len(
                [item for item in practice_items if item.get("sourceType") == "external_assessment"]
            ),
            "sourceCount": len({source for item in items for source in item.get("sourceRefs") or []}),
            "lastUpdated": _last_updated(raw_items),
        }
    return {
        "modelVersion": ASSESSMENT_MODEL_VERSION,
        "dimensions": dimensions,
        "evidenceCount": len(accepted),
        "effectiveEvidenceCount": len(effective),
        "assessedDimensionCount": len([item for item in dimensions.values() if item["evidenceCount"] > 0]),
        "ratedDimensionCount": len([item for item in dimensions.values() if item["ratingReady"]]),
    }


def assessment_to_score_map(assessment: dict[str, Any]) -> dict[str, float]:
    dimensions = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
    scores: dict[str, float] = {}
    for dimension_id in CNC_JOB_CAPABILITY_WEIGHTS:
        result = dimensions.get(dimension_id) if isinstance(dimensions.get(dimension_id), dict) else {}
        score = _float(result.get("score"), 0.0)
        scores[dimension_id] = round(score) if result.get("ratingReady") else 0
        scores[f"{dimension_id}_assessed"] = 1 if result.get("ratingReady") else 0
        scores[f"{dimension_id}_confidence"] = round(_float(result.get("confidence"), 0.0) * 100)
        scores[f"{dimension_id}_provisional"] = round(score)

    weighted_total = 0.0
    provisional_weighted_total = 0.0
    for dimension_id, weight in CNC_JOB_CAPABILITY_WEIGHTS.items():
        result = dimensions.get(dimension_id) if isinstance(dimensions.get(dimension_id), dict) else {}
        score = _float(result.get("score"), 0.0)
        provisional_weighted_total += score * (weight / 100)
        if result.get("ratingReady"):
            weighted_total += score * (weight / 100)

    scores["theory"] = round(_average_rated(assessment, ["foundations", "process_planning", "quality_control"]))
    safety = dimensions.get("safety") if isinstance(dimensions.get("safety"), dict) else {}
    scores["safety"] = round(_float(safety.get("score"), 0.0)) if safety.get("ratingReady") else 0
    scores["operation"] = round(_average_rated(assessment, ["machining_operation", "quality_control", "maintenance"]))
    programming = dimensions.get("programming") if isinstance(dimensions.get("programming"), dict) else {}
    scores["programming"] = (
        round(_float(programming.get("score"), 0.0)) if programming.get("ratingReady") else 0
    )
    scores["overall"] = round(weighted_total)
    scores["provisional_overall"] = round(provisional_weighted_total)
    confidence_values = [
        _float(result.get("confidence"), 0.0)
        for result in dimensions.values()
        if isinstance(result, dict)
    ]
    scores["assessment_confidence"] = round(
        (sum(confidence_values) / len(CNC_JOB_CAPABILITY_WEIGHTS)) * 100
    )
    return scores


def effective_capability_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(
        [item for item in evidence if _valid_evidence(item) and _evidence_is_reviewed(item)],
        key=lambda item: _timestamp(item.get("occurredAt")),
    )
    seen_items: set[str] = set()
    seen_attempt_knowledge: set[str] = set()
    result = []
    for item in sorted_items:
        fingerprint = f"{item.get('dimension')}|{item.get('itemRevision') or item.get('id')}"
        knowledge_id = item.get("knowledgePointId") or _normalize_knowledge_point_id(item.get("knowledgePoint"))
        attempt_knowledge = f"{item.get('attemptId')}|{item.get('dimension')}|{knowledge_id}"
        if fingerprint in seen_items or attempt_knowledge in seen_attempt_knowledge:
            continue
        seen_items.add(fingerprint)
        seen_attempt_knowledge.add(attempt_knowledge)
        result.append(item)
    return result


def capability_evidence_weight(item: dict[str, Any], now: datetime) -> float:
    grader_confidence = item.get("graderConfidence")
    grader_reliability = (
        0.35 + min(max(_float(grader_confidence, 0.0), 0.0), 1.0) * 0.65
        if isinstance(grader_confidence, (int, float))
        else 1.0
    )
    return (
        DIFFICULTY_WEIGHT.get(str(item.get("difficulty") or "easy"), 1.0)
        * _recency_weight(str(item.get("occurredAt") or ""), now)
        * SOURCE_RELIABILITY.get(str(item.get("sourceType") or "quiz"), 1.0)
        * DIMENSION_SOURCE_RELIABILITY.get(str(item.get("dimensionSource") or "fallback"), 0.5)
        * grader_reliability
    )


def _calculate_score_slice(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    if not items:
        return {
            "score": None,
            "observedScore": None,
            "weightedAccuracy": None,
            "effectiveWeight": 0,
            "confidence": 0,
            "status": "unassessed",
            "knowledgePointCount": 0,
            "independentAttemptCount": 0,
        }
    earned_weight = 0.0
    possible_weight = 0.0
    for item in items:
        weight = capability_evidence_weight(item, now)
        earned_weight += (_float(item.get("earned"), 0.0) / _positive_float(item.get("possible"), 1.0)) * weight
        possible_weight += weight
    weighted_accuracy = max(0.0, min(1.0, earned_weight / possible_weight)) if possible_weight else None
    estimated = None
    if weighted_accuracy is not None:
        estimated = (
            earned_weight
            + CAPABILITY_RATING_POLICY["prior_mean"] * CAPABILITY_RATING_POLICY["prior_strength"]
        ) / (possible_weight + CAPABILITY_RATING_POLICY["prior_strength"])
    knowledge_point_count = len(
        {item.get("knowledgePointId") or _normalize_knowledge_point_id(item.get("knowledgePoint")) for item in items}
    )
    independent_attempt_count = len({str(item.get("attemptId") or "") for item in items})
    grounded_count = len([item for item in items if item.get("questionGrounded")])
    volume_confidence = min(1.0, len(items) / CAPABILITY_RATING_POLICY["evidence_for_full_confidence"])
    diversity_confidence = min(
        1.0,
        knowledge_point_count / CAPABILITY_RATING_POLICY["knowledge_points_for_full_confidence"],
    )
    attempt_confidence = min(
        1.0,
        independent_attempt_count / CAPABILITY_RATING_POLICY["attempts_for_full_confidence"],
    )
    grounding_confidence = grounded_count / len(items)
    confidence = min(
        1.0,
        volume_confidence * 0.45
        + diversity_confidence * 0.25
        + attempt_confidence * 0.2
        + grounding_confidence * 0.1,
    )
    rated = (
        len(items) >= CAPABILITY_RATING_POLICY["minimum_effective_evidence"]
        and knowledge_point_count >= CAPABILITY_RATING_POLICY["minimum_knowledge_points"]
        and independent_attempt_count >= CAPABILITY_RATING_POLICY["minimum_independent_attempts"]
        and confidence >= CAPABILITY_RATING_POLICY["minimum_confidence"]
    )
    return {
        "score": round(estimated * 100) if estimated is not None else None,
        "observedScore": round(weighted_accuracy * 100) if weighted_accuracy is not None else None,
        "weightedAccuracy": weighted_accuracy,
        "effectiveWeight": round(possible_weight, 2),
        "confidence": round(confidence, 2),
        "status": "rated" if rated else "insufficient",
        "knowledgePointCount": knowledge_point_count,
        "independentAttemptCount": independent_attempt_count,
    }


def _valid_evidence(item: dict[str, Any]) -> bool:
    earned = _float(item.get("earned"), -1.0)
    possible = _float(item.get("possible"), 0.0)
    return (
        item.get("dimension") in CAPABILITY_DIMENSION_IDS
        and possible > 0
        and earned >= 0
        and earned <= possible
    )


def _evidence_is_reviewed(item: dict[str, Any]) -> bool:
    if item.get("reviewStatus") == "rejected":
        return False
    if item.get("sourceType") == "quiz":
        return item.get("reviewStatus") != "pending_review"
    if item.get("sourceType") == "external_assessment":
        return item.get("reviewStatus") in {"reviewed", "auto_verified"}
    return item.get("reviewStatus") == "reviewed"


def _recency_weight(occurred_at: str, now: datetime) -> float:
    timestamp = _timestamp(occurred_at)
    if timestamp is None:
        return 1.0
    age_days = max(0.0, (now.timestamp() - timestamp) / 86_400)
    return 0.5 ** (age_days / 180)


def _timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _last_updated(items: list[dict[str, Any]]) -> str | None:
    dated = [item for item in items if _timestamp(item.get("occurredAt")) is not None]
    if not dated:
        return None
    return str(max(dated, key=lambda item: _timestamp(item.get("occurredAt")) or 0).get("occurredAt") or "")


def _confidence_label(evidence_count: int, confidence: float) -> str:
    if not evidence_count:
        return "待评估"
    if confidence >= 0.75:
        return "高"
    if confidence >= 0.4:
        return "中"
    return "低"


def _mastery_label(score: int | None, status: str) -> str:
    if score is None:
        return "待评估"
    if status != "rated":
        return "证据不足"
    if score < 50:
        return "需巩固"
    if score < 65:
        return "入门"
    if score < 85:
        return "基本掌握"
    return "熟练"


def _average_rated(assessment: dict[str, Any], dimension_ids: list[str]) -> float:
    dimensions = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
    values = []
    for dimension_id in dimension_ids:
        result = dimensions.get(dimension_id) if isinstance(dimensions.get(dimension_id), dict) else {}
        if result.get("ratingReady") and result.get("score") is not None:
            values.append(_float(result.get("score"), 0.0))
    return sum(values) / len(values) if values else 0.0


def _normalize_knowledge_point_id(value: Any) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())[:180]


def _positive_float(value: Any, default: float) -> float:
    return max(_float(value, default), 0.0001)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
