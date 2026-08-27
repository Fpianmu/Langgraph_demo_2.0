from __future__ import annotations


CNC_JOB_CAPABILITY_WEIGHTS: dict[str, int] = {
    "safety": 15,
    "foundations": 12,
    "process_planning": 14,
    "programming": 16,
    "machining_operation": 18,
    "quality_control": 10,
    "maintenance": 8,
    "advanced_manufacturing": 7,
}

CAPABILITY_RATING_POLICY = {
    "prior_mean": 0.5,
    "prior_strength": 4,
    "minimum_effective_evidence": 4,
    "minimum_knowledge_points": 3,
    "minimum_independent_attempts": 2,
    "minimum_confidence": 0.4,
    "evidence_for_full_confidence": 8,
    "knowledge_points_for_full_confidence": 4,
    "attempts_for_full_confidence": 3,
}

SOURCE_RELIABILITY: dict[str, float] = {
    "quiz": 1.0,
    "practice": 1.5,
    "external_assessment": 2.0,
}

DIFFICULTY_WEIGHT: dict[str, float] = {
    "easy": 1.0,
    "medium": 1.2,
    "hard": 1.5,
}

DIMENSION_SOURCE_RELIABILITY: dict[str, float] = {
    "declared": 1.0,
    "keyword": 0.8,
    "fallback": 0.5,
}
