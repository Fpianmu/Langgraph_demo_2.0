import type { ScoreMap } from "./agent-contract.ts";
import {
  ASSESSMENT_MODEL_VERSION,
  CAPABILITY_DIMENSIONS,
  calculateCapabilityAssessment,
  normalizeCapabilityEvidence,
  type CapabilityAssessment,
  type CapabilityDimensionId,
  type CapabilityDimensionResult,
  type CapabilityEvidence,
} from "./capability-assessment.ts";

export type CapabilityProfileScore = {
  overall: number;
  dimensions: Record<CapabilityDimensionId, number>;
  source: string;
  updatedAt: string;
  dimensionCount: number;
};

export type CapabilityScoresState = {
  userId: string;
  assessment: CapabilityAssessment;
  profileScore: CapabilityProfileScore;
  scores: ScoreMap;
  evidence: CapabilityEvidence[];
  modelVersion: string;
  policyVersion: string;
  updatedAt: string;
  summary: Record<string, unknown>;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function boundedScore(value: unknown): number {
  return Math.max(0, Math.min(100, finite(value)));
}

function nullableScore(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : null;
}

function normalizeDimension(
  id: CapabilityDimensionId,
  value: unknown,
  profileValue: number,
): CapabilityDimensionResult {
  const empty = calculateCapabilityAssessment([]).dimensions[id];
  const source = record(value);
  const ratingStatus =
    source.ratingStatus === "rated" ||
    source.ratingStatus === "insufficient" ||
    source.ratingStatus === "unassessed"
      ? source.ratingStatus
      : empty.ratingStatus;
  const knowledgeStatus =
    source.knowledgeStatus === "rated" ||
    source.knowledgeStatus === "insufficient" ||
    source.knowledgeStatus === "unassessed"
      ? source.knowledgeStatus
      : empty.knowledgeStatus;
  const practiceStatus =
    source.practiceStatus === "rated" ||
    source.practiceStatus === "insufficient" ||
    source.practiceStatus === "unassessed"
      ? source.practiceStatus
      : empty.practiceStatus;

  return {
    ...empty,
    ...source,
    id,
    label: typeof source.label === "string" ? source.label : empty.label,
    shortLabel:
      typeof source.shortLabel === "string" ? source.shortLabel : empty.shortLabel,
    description:
      typeof source.description === "string" ? source.description : empty.description,
    evidenceHint:
      typeof source.evidenceHint === "string" ? source.evidenceHint : empty.evidenceHint,
    keywords: Array.isArray(source.keywords)
      ? source.keywords.filter((item): item is string => typeof item === "string")
      : empty.keywords,
    // capability_profile_score is the authoritative value used by every radar.
    score: profileValue,
    observedScore: nullableScore(source.observedScore),
    weightedAccuracy:
      source.weightedAccuracy === null
        ? null
        : Number.isFinite(Number(source.weightedAccuracy))
          ? Number(source.weightedAccuracy)
          : null,
    evidenceCount: Math.max(0, Math.trunc(finite(source.evidenceCount))),
    effectiveEvidenceCount: Math.max(
      0,
      Math.trunc(finite(source.effectiveEvidenceCount)),
    ),
    knowledgePointCount: Math.max(0, Math.trunc(finite(source.knowledgePointCount))),
    independentAttemptCount: Math.max(
      0,
      Math.trunc(finite(source.independentAttemptCount)),
    ),
    effectiveWeight: Math.max(0, finite(source.effectiveWeight)),
    confidence: Math.max(0, Math.min(1, finite(source.confidence))),
    confidenceLabel:
      source.confidenceLabel === "低" ||
      source.confidenceLabel === "中" ||
      source.confidenceLabel === "高" ||
      source.confidenceLabel === "待评估"
        ? source.confidenceLabel
        : empty.confidenceLabel,
    masteryLabel:
      source.masteryLabel === "待评估" ||
      source.masteryLabel === "证据不足" ||
      source.masteryLabel === "需巩固" ||
      source.masteryLabel === "入门" ||
      source.masteryLabel === "基本掌握" ||
      source.masteryLabel === "熟练"
        ? source.masteryLabel
        : empty.masteryLabel,
    ratingStatus,
    ratingReady: source.ratingReady === true,
    knowledgeScore: nullableScore(source.knowledgeScore),
    knowledgeObservedScore: nullableScore(source.knowledgeObservedScore),
    knowledgeStatus,
    knowledgeEvidenceCount: Math.max(
      0,
      Math.trunc(finite(source.knowledgeEvidenceCount)),
    ),
    practiceScore: nullableScore(source.practiceScore),
    practiceObservedScore: nullableScore(source.practiceObservedScore),
    practiceStatus,
    practiceEvidenceCount: Math.max(
      0,
      Math.trunc(finite(source.practiceEvidenceCount)),
    ),
    externalEvidenceCount: Math.max(
      0,
      Math.trunc(finite(source.externalEvidenceCount)),
    ),
    sourceCount: Math.max(0, Math.trunc(finite(source.sourceCount))),
    lastUpdated:
      typeof source.lastUpdated === "string" ? source.lastUpdated : null,
  } as CapabilityDimensionResult;
}

export function normalizeCapabilityScoresPayload(
  value: unknown,
): CapabilityScoresState {
  const payload = record(value);
  const document = record(payload.capability_assessment);
  const backendAssessment = record(document.assessment);
  const backendDimensions = record(backendAssessment.dimensions);
  const rawProfileScore = record(payload.capability_profile_score);
  const rawProfileDimensions = record(rawProfileScore.dimensions);

  const dimensions = Object.fromEntries(
    CAPABILITY_DIMENSIONS.map((definition) => [
      definition.id,
      boundedScore(rawProfileDimensions[definition.id]),
    ]),
  ) as Record<CapabilityDimensionId, number>;
  const profileScore: CapabilityProfileScore = {
    overall: boundedScore(rawProfileScore.overall),
    dimensions,
    source:
      typeof rawProfileScore.source === "string"
        ? rawProfileScore.source
        : "capability_assessment.score_map",
    updatedAt:
      typeof rawProfileScore.updated_at === "string"
        ? rawProfileScore.updated_at
        : "",
    dimensionCount: Math.max(
      0,
      Math.trunc(finite(rawProfileScore.dimension_count)),
    ),
  };

  const assessment: CapabilityAssessment = {
    modelVersion: ASSESSMENT_MODEL_VERSION,
    dimensions: Object.fromEntries(
      CAPABILITY_DIMENSIONS.map((definition) => [
        definition.id,
        normalizeDimension(
          definition.id,
          backendDimensions[definition.id],
          dimensions[definition.id],
        ),
      ]),
    ) as CapabilityAssessment["dimensions"],
    evidenceCount: Math.max(0, Math.trunc(finite(backendAssessment.evidenceCount))),
    effectiveEvidenceCount: Math.max(
      0,
      Math.trunc(finite(backendAssessment.effectiveEvidenceCount)),
    ),
    assessedDimensionCount: Math.max(
      0,
      Math.trunc(finite(backendAssessment.assessedDimensionCount)),
    ),
    ratedDimensionCount: Math.max(
      0,
      Math.trunc(finite(backendAssessment.ratedDimensionCount)),
    ),
  };

  const rawScores = record(payload.scores);
  const scores = Object.fromEntries(
    Object.entries(rawScores)
      .map(([key, item]) => [key, finite(item)] as const),
  ) as ScoreMap;
  scores.theory = finite(rawScores.theory);
  scores.safety = finite(rawScores.safety);
  scores.operation = finite(rawScores.operation);
  for (const definition of CAPABILITY_DIMENSIONS) {
    scores[definition.id] = dimensions[definition.id];
  }
  scores.overall = profileScore.overall;

  return {
    userId: typeof payload.user_id === "string" ? payload.user_id : "",
    assessment,
    profileScore,
    scores,
    evidence: normalizeCapabilityEvidence(document.evidence),
    modelVersion:
      typeof document.model_version === "string"
        ? document.model_version
        : ASSESSMENT_MODEL_VERSION,
    policyVersion:
      typeof document.policy_version === "string" ? document.policy_version : "",
    updatedAt:
      typeof document.updated_at === "string" ? document.updated_at : profileScore.updatedAt,
    summary: record(document.summary),
  };
}

export async function loadCapabilityScores(
  userId: string,
): Promise<CapabilityScoresState> {
  const response = await fetch(
    `/api/storage/users/${encodeURIComponent(userId)}/scores`,
    { cache: "no-store" },
  );
  const data = (await response.json()) as Record<string, unknown> & {
    error?: string;
  };
  if (!response.ok) {
    throw new Error(data.error || `八维能力接口返回 HTTP ${response.status}`);
  }
  return normalizeCapabilityScoresPayload(data);
}
