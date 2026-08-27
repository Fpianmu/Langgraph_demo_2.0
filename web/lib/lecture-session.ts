import type { AgentResponse } from "./agent-contract.ts";
import type {
  CapabilityDimensionId,
  CapabilityEvidence,
} from "./capability-assessment.ts";
import {
  capabilityEvidenceWeight,
  effectiveCapabilityEvidence,
} from "./capability-assessment.ts";
import { COURSE_CHAPTERS } from "./learning-progress.ts";
import { LECTURE_RATING_POLICY } from "./scoring-policy.ts";

export const LECTURE_SESSION_MODEL_VERSION = "zlink-lecture-session-v2";
export const LECTURE_MASTERY_MODEL_VERSION = "zlink-lecture-mastery-v2";
export const MAX_PERSISTED_LECTURES = 50;

export type LectureSection = {
  heading: string;
  content: string;
};

export type LectureGenerationReason = "initial" | "regenerate" | "next_stage";

export type LectureSession = {
  modelVersion: typeof LECTURE_SESSION_MODEL_VERSION;
  id: string;
  requestId: string;
  courseId: string;
  chapterId: string;
  chapterTitle: string;
  title: string;
  summary: string;
  sections: LectureSection[];
  targetDimensions: CapabilityDimensionId[];
  objectiveIds: string[];
  baselineEvidenceIds: string[];
  sourceRefs: string[];
  ragChunkIds: string[];
  ragConfidence: number | null;
  knowledgeBaseVersion: string | null;
  artifactPath: string;
  generationReason: LectureGenerationReason;
  predecessorId: string | null;
  createdAt: string;
};

export type LectureMastery = {
  modelVersion: typeof LECTURE_MASTERY_MODEL_VERSION;
  status: "not_assessed" | "learning" | "mastered";
  score: number | null;
  observedScore: number | null;
  confidence: number;
  evidenceCount: number;
  effectiveEvidenceCount: number;
  knowledgePointCount: number;
  independentAttemptCount: number;
  practiceEvidenceCount: number;
  weightedAccuracy: number | null;
  safetyScore: number | null;
  recommendedForNextStage: boolean;
  message: string;
  requirements: Array<{
    label: string;
    passed: boolean;
    current: string;
    requirement: string;
  }>;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function cleanString(value: unknown, max = 100_000): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

function uniqueStrings(values: unknown[], max = 200): string[] {
  return [
    ...new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ].slice(0, max);
}

function validDate(value: unknown, fallback: string): string {
  const text = cleanString(value, 80);
  return text && Number.isFinite(new Date(text).getTime()) ? text : fallback;
}

function lectureCandidates(response: AgentResponse): Record<string, unknown>[] {
  const root = asRecord(response);
  const finalOutput = asRecord(root?.final_output);
  const finalMaterials = asRecord(root?.final_materials);
  const nestedMaterials = asRecord(finalOutput?.materials);
  return [
    root?.personalized_lecture_output,
    root?.final_lecture_output,
    finalMaterials?.lecture,
    nestedMaterials?.lecture,
    finalOutput,
  ]
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => !!item);
}

function parseSections(value: unknown): LectureSection[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate, index) => {
    const item = asRecord(candidate);
    const heading = cleanString(item?.heading ?? item?.title, 300);
    const content = cleanString(item?.content ?? item?.body, 50_000);
    if (!content) return [];
    return [{ heading: heading || `第 ${index + 1} 节`, content }];
  });
}

export function defaultDimensionsForChapter(
  chapterId: string,
): CapabilityDimensionId[] {
  const exact: Record<string, CapabilityDimensionId[]> = {
    "1.1": ["foundations"],
    "1.2": ["foundations"],
    "1.3": ["foundations", "process_planning"],
    "1.4": ["foundations", "quality_control"],
    "1.5": ["foundations", "safety"],
    "2.1": ["machining_operation", "foundations"],
    "2.2": ["machining_operation", "safety"],
    "2.3": ["safety", "machining_operation", "maintenance"],
    "2.4": ["safety", "machining_operation"],
    "2.5": ["safety", "machining_operation"],
    "3.1": ["foundations", "process_planning"],
    "3.2": ["machining_operation", "process_planning", "quality_control"],
    "3.3": ["machining_operation", "process_planning", "quality_control"],
    "3.4": ["programming", "machining_operation", "quality_control"],
    "3.5": ["quality_control", "machining_operation"],
    "4.1": ["process_planning", "programming", "machining_operation"],
    "4.2": ["process_planning", "machining_operation", "quality_control"],
    "4.3": ["quality_control", "foundations"],
    "4.4": ["quality_control", "process_planning"],
    "4.5": ["maintenance", "quality_control", "advanced_manufacturing"],
  };
  return exact[chapterId] ?? ["foundations"];
}

export function nextCourseChapter(chapterId: string): {
  id: string;
  title: string;
} | null {
  const index = COURSE_CHAPTERS.findIndex(([id]) => id === chapterId);
  const next = index >= 0 ? COURSE_CHAPTERS[index + 1] : undefined;
  return next ? { id: next[0], title: next[1] } : null;
}

function artifactPath(response: AgentResponse): string {
  const root = asRecord(response);
  const direct = asRecord(root?.lecture_artifact_paths);
  const saved = asRecord(root?.saved_lecture_artifact);
  const savedOutputs = asRecord(root?.saved_outputs);
  const savedLecture = asRecord(savedOutputs?.lecture);
  return cleanString(
    direct?.markdown ?? saved?.markdown_path ?? savedLecture?.markdown_path,
    1_000,
  );
}

export function createLectureSession(input: {
  id: string;
  courseId: string;
  chapterId: string;
  response: AgentResponse;
  capabilityEvidence: CapabilityEvidence[];
  generationReason: LectureGenerationReason;
  predecessorId?: string | null;
  createdAt?: string;
}): LectureSession {
  const timestamp = input.createdAt ?? new Date().toISOString();
  let title = "";
  let summary = "";
  let sections: LectureSection[] = [];
  for (const output of lectureCandidates(input.response)) {
    const payload = asRecord(output.payload) ?? output;
    const parsed = parseSections(payload.sections ?? output.sections);
    const content = cleanString(payload.content ?? output.content, 100_000);
    if (!parsed.length && content) {
      parsed.push({ heading: "讲义正文", content });
    }
    if (!parsed.length) continue;
    title = cleanString(output.title ?? payload.title, 500);
    summary = cleanString(output.summary ?? payload.summary, 2_000);
    sections = parsed;
    break;
  }
  if (!sections.length) {
    throw new Error("中央调度器未返回符合接口协议的讲义内容");
  }
  const evidence = input.response.rag_package?.evidence ?? [];
  const citations = input.response.rag_package?.citations ?? [];
  const sourceRefs = uniqueStrings([
    ...(input.response.final_output?.evidence_refs ?? []),
    ...evidence.map((item) => item.source_file ?? item.source_doc),
    ...citations.map((item) => item.source_file ?? item.source_doc),
  ]);
  const ragChunkIds = uniqueStrings([
    ...evidence.map((item) => item.chunk_id),
    ...citations.map((item) => item.chunk_id),
  ]);
  const confidence = Number(input.response.rag_package?.confidence);
  const chapterTitle =
    COURSE_CHAPTERS.find(([id]) => id === input.chapterId)?.[1] ?? input.chapterId;
  return {
    modelVersion: LECTURE_SESSION_MODEL_VERSION,
    id: input.id,
    requestId: input.response.request_id,
    courseId: input.courseId,
    chapterId: input.chapterId,
    chapterTitle,
    title: title || `${chapterTitle}学习讲义`,
    summary: summary || `根据当前用户画像和知识库生成的“${chapterTitle}”讲义。`,
    sections,
    targetDimensions: defaultDimensionsForChapter(input.chapterId),
    objectiveIds: defaultDimensionsForChapter(input.chapterId).map(
      (dimension) => `${input.chapterId}:${dimension}`,
    ),
    baselineEvidenceIds: uniqueStrings(input.capabilityEvidence.map((item) => item.id), 2_000),
    sourceRefs,
    ragChunkIds,
    ragConfidence: Number.isFinite(confidence)
      ? Math.max(0, Math.min(1, confidence))
      : null,
    knowledgeBaseVersion:
      cleanString(input.response.rag_package?.knowledge_base_version, 200) || null,
    artifactPath: artifactPath(input.response),
    generationReason: input.generationReason,
    predecessorId: input.predecessorId ?? null,
    createdAt: timestamp,
  };
}

export function upsertLectureSession(
  sessions: LectureSession[],
  session: LectureSession,
): LectureSession[] {
  return [session, ...sessions.filter((item) => item.id !== session.id)]
    .sort(
      (a, b) =>
        new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    )
    .slice(0, MAX_PERSISTED_LECTURES);
}

export function calculateLectureMastery(
  lecture: LectureSession,
  evidence: CapabilityEvidence[],
): LectureMastery {
  // v2 requires an explicit lecture link. A broad capability match is not
  // enough to prove that this lecture's objectives were assessed.
  const linked = evidence.filter(
    (item) =>
      item.lectureId === lecture.id &&
      item.chapterId === lecture.chapterId &&
      (item.objectiveIds ?? []).some((objectiveId) =>
        lecture.objectiveIds.includes(objectiveId),
      ) &&
      lecture.targetDimensions.includes(item.dimension),
  );
  const relevant = effectiveCapabilityEvidence(linked);
  let possible = 0;
  let earned = 0;
  const now = new Date();
  for (const item of relevant) {
    const weight = capabilityEvidenceWeight(item, now);
    possible += weight;
    earned += (item.earned / item.possible) * weight;
  }
  const accuracy = possible > 0 ? earned / possible : null;
  const points = new Set(
    relevant.map((item) => item.knowledgePointId).filter(Boolean),
  );
  const independentAttempts = new Set(relevant.map((item) => item.attemptId));
  const groundedCount = relevant.filter((item) => item.questionGrounded).length;
  const practiceEvidence = relevant.filter(
    (item) => item.sourceType === "practice" || item.sourceType === "external_assessment",
  );
  const safetyEvidence = relevant.filter((item) => item.dimension === "safety");
  const safetyPossible = safetyEvidence.reduce((sum, item) => sum + item.possible, 0);
  const safetyScore = safetyPossible
    ? Math.round(
        (safetyEvidence.reduce((sum, item) => sum + item.earned, 0) /
          safetyPossible) *
          100,
      )
    : null;
  const accuracyScore = accuracy === null ? null : Math.round(accuracy * 100);
  const confidence = relevant.length
    ? Math.min(
        1,
        Math.min(1, relevant.length / LECTURE_RATING_POLICY.minimumEffectiveEvidence) * 0.45 +
          Math.min(1, points.size / LECTURE_RATING_POLICY.minimumKnowledgePoints) * 0.25 +
          Math.min(1, independentAttempts.size / LECTURE_RATING_POLICY.minimumIndependentAttempts) * 0.2 +
          (groundedCount / relevant.length) * 0.1,
      )
    : 0;
  const scoreReady =
    relevant.length >= LECTURE_RATING_POLICY.minimumEffectiveEvidence &&
    points.size >= LECTURE_RATING_POLICY.minimumKnowledgePoints &&
    independentAttempts.size >= LECTURE_RATING_POLICY.minimumIndependentAttempts &&
    confidence >= LECTURE_RATING_POLICY.minimumConfidence;
  const score = scoreReady ? accuracyScore : null;
  const safetyRequired = lecture.targetDimensions.includes("safety");
  const practiceRequired = lecture.targetDimensions.some((dimension) =>
    ["machining_operation", "quality_control", "maintenance"].includes(dimension),
  );
  const requirements = [
    {
      label: "讲义后有效评价",
      passed: relevant.length >= LECTURE_RATING_POLICY.minimumEffectiveEvidence,
      current: `${relevant.length} 条`,
      requirement: `≥ ${LECTURE_RATING_POLICY.minimumEffectiveEvidence} 条`,
    },
    {
      label: "相关知识点覆盖",
      passed: points.size >= LECTURE_RATING_POLICY.minimumKnowledgePoints,
      current: `${points.size} 个`,
      requirement: `≥ ${LECTURE_RATING_POLICY.minimumKnowledgePoints} 个`,
    },
    {
      label: "独立复测",
      passed:
        independentAttempts.size >=
        LECTURE_RATING_POLICY.minimumIndependentAttempts,
      current: `${independentAttempts.size} 次`,
      requirement: `≥ ${LECTURE_RATING_POLICY.minimumIndependentAttempts} 次`,
    },
    {
      label: "相关题目正确率",
      passed:
        accuracy !== null && accuracy >= LECTURE_RATING_POLICY.minimumAccuracy,
      current: accuracy === null ? "待评估" : `${accuracyScore}%`,
      requirement: `≥ ${Math.round(LECTURE_RATING_POLICY.minimumAccuracy * 100)}%`,
    },
    {
      label: "评价可信度",
      passed: confidence >= LECTURE_RATING_POLICY.minimumConfidence,
      current: `${Math.round(confidence * 100)}%`,
      requirement: `≥ ${Math.round(LECTURE_RATING_POLICY.minimumConfidence * 100)}%`,
    },
    ...(safetyRequired
      ? [
          {
            label: "安全知识正确率",
            passed:
              safetyScore !== null &&
              safetyScore >= LECTURE_RATING_POLICY.minimumSafetyAccuracy * 100,
            current: safetyScore === null ? "待评估" : `${safetyScore}%`,
            requirement: `≥ ${Math.round(LECTURE_RATING_POLICY.minimumSafetyAccuracy * 100)}%`,
          },
        ]
      : []),
    ...(practiceRequired
      ? [
          {
            label: "已审核实操证据",
            passed:
              practiceEvidence.length >=
              LECTURE_RATING_POLICY.minimumReviewedPractice,
            current: `${practiceEvidence.length} 条`,
            requirement: `≥ ${LECTURE_RATING_POLICY.minimumReviewedPractice} 条`,
          },
        ]
      : []),
  ];
  const mastered = requirements.every((item) => item.passed);
  const status = relevant.length === 0 ? "not_assessed" : mastered ? "mastered" : "learning";
  return {
    modelVersion: LECTURE_MASTERY_MODEL_VERSION,
    status,
    score,
    observedScore: accuracyScore,
    confidence: Number(confidence.toFixed(2)),
    evidenceCount: linked.length,
    effectiveEvidenceCount: relevant.length,
    knowledgePointCount: points.size,
    independentAttemptCount: independentAttempts.size,
    practiceEvidenceCount: practiceEvidence.length,
    weightedAccuracy: accuracy,
    safetyScore,
    recommendedForNextStage: mastered,
    message: mastered
      ? "你已较好掌握当前知识，可以进一步进行学习啦"
      : relevant.length
        ? "当前作答已记录，但证据量、覆盖或独立复测尚未达标"
        : "尚无与本讲义目标精确关联的评价证据",
    requirements,
  };
}

export function normalizeLectureSessions(value: unknown): LectureSession[] {
  if (!Array.isArray(value)) return [];
  const now = new Date().toISOString();
  return value.flatMap((candidate) => {
    const item = asRecord(candidate);
    const id = cleanString(item?.id, 150);
    const sections = parseSections(item?.sections);
    if (!item || !id || !sections.length) return [];
    const chapterId = cleanString(item.chapterId, 100) || "1.1";
    const targetDimensions = Array.isArray(item.targetDimensions)
      ? item.targetDimensions.filter((dimension): dimension is CapabilityDimensionId =>
          [
            "safety",
            "foundations",
            "process_planning",
            "programming",
            "machining_operation",
            "quality_control",
            "maintenance",
            "advanced_manufacturing",
          ].includes(String(dimension)),
        )
      : defaultDimensionsForChapter(chapterId);
    const reason: LectureGenerationReason =
      item.generationReason === "regenerate" || item.generationReason === "next_stage"
        ? item.generationReason
        : "initial";
    const session: LectureSession = {
      modelVersion: LECTURE_SESSION_MODEL_VERSION,
      id,
      requestId: cleanString(item.requestId, 200),
      courseId: cleanString(item.courseId, 200) || "cnc_lathe",
      chapterId,
      chapterTitle:
        cleanString(item.chapterTitle, 500) ||
        COURSE_CHAPTERS.find(([chapter]) => chapter === chapterId)?.[1] ||
        chapterId,
      title: cleanString(item.title, 500) || "未命名讲义",
      summary: cleanString(item.summary, 2_000),
      sections,
      targetDimensions:
        targetDimensions.length > 0
          ? [...new Set(targetDimensions)]
          : defaultDimensionsForChapter(chapterId),
      objectiveIds: Array.isArray(item.objectiveIds)
        ? uniqueStrings(item.objectiveIds)
        : (targetDimensions.length > 0
            ? [...new Set(targetDimensions)]
            : defaultDimensionsForChapter(chapterId)
          ).map((dimension) => `${chapterId}:${dimension}`),
      baselineEvidenceIds: uniqueStrings(
        Array.isArray(item.baselineEvidenceIds) ? item.baselineEvidenceIds : [],
        2_000,
      ),
      sourceRefs: uniqueStrings(Array.isArray(item.sourceRefs) ? item.sourceRefs : []),
      ragChunkIds: uniqueStrings(Array.isArray(item.ragChunkIds) ? item.ragChunkIds : []),
      ragConfidence: Number.isFinite(Number(item.ragConfidence))
        ? Math.max(0, Math.min(1, Number(item.ragConfidence)))
        : null,
      knowledgeBaseVersion: cleanString(item.knowledgeBaseVersion, 200) || null,
      artifactPath: cleanString(item.artifactPath, 1_000),
      generationReason: reason,
      predecessorId: cleanString(item.predecessorId, 150) || null,
      createdAt: validDate(item.createdAt, now),
    };
    return [session];
  }).sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    .slice(0, MAX_PERSISTED_LECTURES);
}
