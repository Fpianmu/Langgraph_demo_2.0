import type { CapabilityDimensionId } from "./capability-assessment.ts";

/**
 * Shared v2 policy. Keeping the weights in one module prevents Memory and the
 * learning-progress page from producing two different "overall" scores.
 */
export const CNC_JOB_CAPABILITY_WEIGHTS: Record<CapabilityDimensionId, number> = {
  safety: 15,
  foundations: 12,
  process_planning: 14,
  programming: 16,
  machining_operation: 18,
  quality_control: 10,
  maintenance: 8,
  advanced_manufacturing: 7,
};

export const CAPABILITY_RATING_POLICY = {
  /** A neutral prior prevents one correct answer from becoming 100 ability. */
  priorMean: 0.5,
  priorStrength: 4,
  minimumEffectiveEvidence: 4,
  minimumKnowledgePoints: 3,
  minimumIndependentAttempts: 2,
  minimumConfidence: 0.4,
  evidenceForFullConfidence: 8,
  knowledgePointsForFullConfidence: 4,
  attemptsForFullConfidence: 3,
} as const;

export const LECTURE_RATING_POLICY = {
  minimumEffectiveEvidence: 8,
  minimumKnowledgePoints: 4,
  minimumIndependentAttempts: 2,
  minimumAccuracy: 0.7,
  minimumConfidence: 0.5,
  minimumSafetyAccuracy: 0.8,
  minimumReviewedPractice: 1,
} as const;

export const SOURCE_RELIABILITY = {
  quiz: 1,
  practice: 1.5,
  external_assessment: 2,
} as const;

export const DIFFICULTY_WEIGHT = {
  easy: 1,
  medium: 1.2,
  hard: 1.5,
} as const;

export const DIMENSION_SOURCE_RELIABILITY = {
  declared: 1,
  keyword: 0.8,
  fallback: 0.5,
} as const;
