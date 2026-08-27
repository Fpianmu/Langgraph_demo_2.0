from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from agent.tools.profile.capability_scoring_policy import CNC_JOB_CAPABILITY_WEIGHTS


RESOURCE_BASE_DIFFICULTY: dict[str, float] = {
    "lecture": 42.0,
    "practice": 56.0,
    "quiz": 62.0,
    "default": 52.0,
}

RESOURCE_DIFFICULTY_BLEND: dict[str, float] = {
    "lecture": 0.78,
    "practice": 0.74,
    "quiz": 0.72,
    "default": 0.75,
}


def build_capability_profile_score(assessment: dict[str, Any]) -> dict[str, Any]:
    score_map = assessment.get("score_map") if isinstance(assessment.get("score_map"), dict) else {}
    dimensions: dict[str, float] = {}
    for dimension_id in CNC_JOB_CAPABILITY_WEIGHTS:
        value = _normalized_dimension_score(score_map, dimension_id)
        if value is None:
            continue
        dimensions[dimension_id] = value

    if dimensions:
        overall = round(sum(dimensions.values()) / len(dimensions), 2)
    else:
        overall = 0.0

    return {
        "overall": overall,
        "dimensions": dimensions,
        "source": "capability_assessment.score_map",
        "updated_at": _now(),
        "dimension_count": len(dimensions),
    }


def resource_difficulty_for(
    profile_score: dict[str, Any] | float | int,
    *,
    resource_type: str,
    resource_id: str,
    chapter_id: str,
    source_node: str = "",
    resource_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_value = _profile_overall(profile_score)
    kind = str(resource_type or "").strip().lower() or "default"
    base = RESOURCE_BASE_DIFFICULTY.get(kind, RESOURCE_BASE_DIFFICULTY["default"])
    blend = RESOURCE_DIFFICULTY_BLEND.get(kind, RESOURCE_DIFFICULTY_BLEND["default"])
    offset = _deterministic_offset(f"{kind}|{resource_id}|{chapter_id}|{source_node}", span=3.5)
    resource_difficulty = _clamp(
        round(profile_value * blend + base * (1.0 - blend) + offset, 2),
    )
    delta = round(resource_difficulty - profile_value, 2)
    alignment_score = round(max(0.0, 100.0 - abs(delta) * 2.5), 2)
    return {
        "resource_id": str(resource_id or ""),
        "resource_type": kind,
        "chapter_id": str(chapter_id or ""),
        "profile_score": round(profile_value, 2),
        "resource_difficulty": resource_difficulty,
        "difficulty_delta": delta,
        "alignment_score": alignment_score,
        "source_node": str(source_node or ""),
        "resource_meta": dict(resource_meta or {}),
        "created_at": _now(),
    }


def _normalized_dimension_score(score_map: dict[str, Any], dimension_id: str) -> float | None:
    rated = _float(score_map.get(dimension_id))
    if rated is not None and rated > 0:
        return round(rated, 2)
    provisional = _float(score_map.get(f"{dimension_id}_provisional"))
    if provisional is not None and provisional > 0:
        return round(provisional, 2)
    return None


def _profile_overall(profile_score: dict[str, Any] | float | int) -> float:
    if isinstance(profile_score, dict):
        overall = _float(profile_score.get("overall"))
        if overall is not None:
            return overall
        dimensions = profile_score.get("dimensions") if isinstance(profile_score.get("dimensions"), dict) else {}
        values = [_float(value) for value in dimensions.values()]
        values = [value for value in values if value is not None and value > 0]
        if values:
            return sum(values) / len(values)
        return 0.0
    value = _float(profile_score)
    return value if value is not None else 0.0


def _deterministic_offset(seed: str, *, span: float) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    scale = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return round((scale * 2.0 - 1.0) * span, 2)


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 100.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
