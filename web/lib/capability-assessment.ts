import type {
  AgentResponse,
  LearnerProfile,
  QuizQuestion,
  ScoreMap,
} from "@/lib/agent-contract";
import {
  CAPABILITY_RATING_POLICY,
  CNC_JOB_CAPABILITY_WEIGHTS,
  DIFFICULTY_WEIGHT,
  DIMENSION_SOURCE_RELIABILITY,
  SOURCE_RELIABILITY,
} from "./scoring-policy.ts";

export const ASSESSMENT_MODEL_VERSION = "cnc-capability-v2";

export type CapabilityDimensionId =
  | "safety"
  | "foundations"
  | "process_planning"
  | "programming"
  | "machining_operation"
  | "quality_control"
  | "maintenance"
  | "advanced_manufacturing";

export type AssessmentDifficulty = "easy" | "medium" | "hard";
export type EvidenceReviewStatus =
  | "auto_verified"
  | "pending_review"
  | "reviewed"
  | "rejected";
export type CapabilityRatingStatus =
  | "unassessed"
  | "insufficient"
  | "rated";

export type CapabilityEvidence = {
  id: string;
  attemptId: string;
  sourceType: "quiz" | "practice" | "external_assessment";
  dimension: CapabilityDimensionId;
  topic: string;
  knowledgePoint: string;
  correct: boolean;
  earned: number;
  possible: number;
  difficulty: AssessmentDifficulty;
  occurredAt: string;
  sourceRefs: string[];
  ragChunkIds: string[];
  questionType?: string;
  gradingMethod?: string;
  rubricVersion?: string;
  semanticScore?: number | null;
  keyPointScore?: number | null;
  graderConfidence?: number | null;
  attemptNumber: number;
  itemRevision: string;
  knowledgePointId: string;
  dimensionSource: "declared" | "keyword" | "fallback";
  questionGrounded: boolean;
  reviewStatus: EvidenceReviewStatus;
  reviewedBy?: string;
  lectureId?: string;
  chapterId?: string;
  objectiveIds: string[];
  criticalSafetyError?: boolean;
};

export type CapabilityAssessmentSnapshot = {
  model_version: typeof ASSESSMENT_MODEL_VERSION;
  evidence: CapabilityEvidence[];
};

export type CapabilityDimensionDefinition = {
  id: CapabilityDimensionId;
  label: string;
  shortLabel: string;
  description: string;
  evidenceHint: string;
  keywords: string[];
};

export type CapabilityDimensionResult = CapabilityDimensionDefinition & {
  /** Bayesian-shrunk ability estimate used by recommendations and readiness. */
  score: number | null;
  /** Raw weighted performance, kept separate so small samples stay visible. */
  observedScore: number | null;
  weightedAccuracy: number | null;
  evidenceCount: number;
  effectiveEvidenceCount: number;
  knowledgePointCount: number;
  independentAttemptCount: number;
  effectiveWeight: number;
  confidence: number;
  confidenceLabel: "待评估" | "低" | "中" | "高";
  masteryLabel:
    | "待评估"
    | "证据不足"
    | "需巩固"
    | "入门"
    | "基本掌握"
    | "熟练";
  ratingStatus: CapabilityRatingStatus;
  ratingReady: boolean;
  knowledgeScore: number | null;
  knowledgeObservedScore: number | null;
  knowledgeStatus: CapabilityRatingStatus;
  knowledgeEvidenceCount: number;
  practiceScore: number | null;
  practiceObservedScore: number | null;
  practiceStatus: CapabilityRatingStatus;
  practiceEvidenceCount: number;
  externalEvidenceCount: number;
  sourceCount: number;
  lastUpdated: string | null;
};

export type CapabilityAssessment = {
  modelVersion: typeof ASSESSMENT_MODEL_VERSION;
  dimensions: Record<CapabilityDimensionId, CapabilityDimensionResult>;
  evidenceCount: number;
  effectiveEvidenceCount: number;
  assessedDimensionCount: number;
  ratedDimensionCount: number;
};

export type QuizAttemptForAssessment = {
  attemptId: string;
  topic: string;
  focus: string;
  difficulty: AssessmentDifficulty;
  occurredAt: string;
  attemptNumber?: number;
  chapterId?: string;
  lectureId?: string;
  objectiveIds?: string[];
  questions: Array<{
    questionId?: string;
    question: QuizQuestion;
    selectedAnswer: string;
    correctAnswer: string;
    earned?: number;
    possible?: number;
    isCorrect?: boolean;
    gradingMethod?: string;
    rubricVersion?: string;
    semanticScore?: number | null;
    keyPointScore?: number | null;
    graderConfidence?: number | null;
    criticalSafetyError?: boolean;
  }>;
  response?: AgentResponse | null;
};

/**
 * The dimensions come from the CNC turning/milling and multi-axis vocational
 * standards plus the junior/intermediate/senior assessment outlines in
 * /resource. They intentionally separate knowledge, planning, programming,
 * execution, inspection and maintenance because those documents assess them
 * independently.
 */
export const CAPABILITY_DIMENSIONS: CapabilityDimensionDefinition[] = [
  {
    id: "safety",
    label: "安全规范与职业素养",
    shortLabel: "安全规范",
    description: "个人防护、开机检查、急停、异常处置、电气安全与 6S 规范",
    evidenceHint: "安全题库、情境判断和规范操作题",
    keywords: [
      "安全",
      "急停",
      "防护",
      "事故",
      "危险",
      "违规",
      "断电",
      "防护门",
      "职业素养",
      "6s",
    ],
  },
  {
    id: "foundations",
    label: "专业基础与识图",
    shortLabel: "基础识图",
    description: "机床原理、坐标系、机械制图、公差、材料与切削基础",
    evidenceHint: "理论题、图纸识读题和概念辨析题",
    keywords: [
      "原理",
      "识图",
      "图纸",
      "机械制图",
      "坐标系",
      "材料",
      "切削基础",
      "基础理论",
      "公差",
    ],
  },
  {
    id: "process_planning",
    label: "工艺分析与加工规划",
    shortLabel: "工艺规划",
    description: "工艺路线、工序安排、刀夹量具选择、装夹方案与切削参数",
    evidenceHint: "工艺案例、工艺卡和方案选择题",
    keywords: [
      "工艺",
      "工序",
      "工步",
      "工艺路线",
      "工艺卡",
      "夹具",
      "装夹方案",
      "切削参数",
      "切削用量",
      "毛坯",
    ],
  },
  {
    id: "programming",
    label: "数控编程与程序校验",
    shortLabel: "数控编程",
    description: "G/M 指令、循环、刀补、手工编程、CAM、仿真与程序校验",
    evidenceHint: "编程题、程序纠错题和仿真校验题",
    keywords: [
      "编程",
      "程序",
      "g代码",
      "m代码",
      "g-code",
      "m-code",
      "循环指令",
      "刀具补偿",
      "刀补",
      "cam",
      "仿真",
      "程序校验",
    ],
  },
  {
    id: "machining_operation",
    label: "机床操作与加工实施",
    shortLabel: "操作加工",
    description: "回零、对刀、装夹、试运行、自动加工与现场参数调整",
    evidenceHint: "操作流程题、模拟实训和实际操作记录",
    keywords: [
      "操作",
      "回零",
      "对刀",
      "装夹",
      "试运行",
      "空运行",
      "首件",
      "试切",
      "加工实施",
      "自动加工",
    ],
  },
  {
    id: "quality_control",
    label: "质量检测与误差控制",
    shortLabel: "质量检测",
    description: "量具使用、尺寸和形位公差、表面质量、误差分析与补偿",
    evidenceHint: "检测题、测量结果和加工质量数据",
    keywords: [
      "质量",
      "检测",
      "测量",
      "量具",
      "精度",
      "误差",
      "误差补偿",
      "粗糙度",
      "形位公差",
      "尺寸公差",
      "自检",
    ],
  },
  {
    id: "maintenance",
    label: "设备维护与故障处理",
    shortLabel: "维护诊断",
    description: "清洁润滑、日常保养、报警识别和机械电气液压故障处理",
    evidenceHint: "报警诊断、故障案例和维护任务",
    keywords: [
      "维护",
      "保养",
      "润滑",
      "报警",
      "故障",
      "诊断",
      "维修",
      "液压",
      "电气系统",
      "冷却系统",
    ],
  },
  {
    id: "advanced_manufacturing",
    label: "先进加工与智能制造",
    shortLabel: "先进制造",
    description: "车铣复合、多轴加工、后处理、远程运维与智能制造应用",
    evidenceHint: "中高级综合题、多轴任务和智能制造案例",
    keywords: [
      "多轴",
      "四轴",
      "五轴",
      "车铣复合",
      "联动",
      "后处理",
      "碰撞检查",
      "智能制造",
      "远程运维",
      "数据采集",
    ],
  },
];

function normalizedText(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[\s_-]+/g, "")
    .trim();
}

export function normalizeKnowledgePointId(value: unknown): string {
  return String(value ?? "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "")
    .slice(0, 180);
}

function itemFingerprint(question: QuizQuestion): string {
  return normalizeKnowledgePointId(question.stem).slice(0, 240);
}

function asDifficulty(value: unknown): AssessmentDifficulty {
  const text = normalizedText(value);
  if (text.includes("hard") || text.includes("进阶") || text.includes("高级")) {
    return "hard";
  }
  if (
    text.includes("medium") ||
    text.includes("中等") ||
    text.includes("中级")
  ) {
    return "medium";
  }
  return "easy";
}

function declaredDimension(value: unknown): CapabilityDimensionId | null {
  const token = normalizedText(value);
  const aliases: Record<string, CapabilityDimensionId> = {
    safety: "safety",
    安全: "safety",
    theory: "foundations",
    foundations: "foundations",
    基础理论: "foundations",
    基础识图: "foundations",
    processplanning: "process_planning",
    工艺规划: "process_planning",
    工艺分析: "process_planning",
    programming: "programming",
    数控编程: "programming",
    operation: "machining_operation",
    machiningoperation: "machining_operation",
    操作加工: "machining_operation",
    qualitycontrol: "quality_control",
    质量检测: "quality_control",
    maintenance: "maintenance",
    维护诊断: "maintenance",
    advancedmanufacturing: "advanced_manufacturing",
    先进制造: "advanced_manufacturing",
    智能制造: "advanced_manufacturing",
  };
  return aliases[token] ?? null;
}

export function classifyCapabilityDimension(input: {
  declared?: unknown;
  topic?: string;
  focus?: string;
  stem?: string;
  explanation?: string;
}): CapabilityDimensionId {
  return classifyCapabilityDimensionWithSource(input).dimension;
}

function classifyCapabilityDimensionWithSource(input: {
  declared?: unknown;
  topic?: string;
  focus?: string;
  stem?: string;
  explanation?: string;
}): {
  dimension: CapabilityDimensionId;
  source: CapabilityEvidence["dimensionSource"];
} {
  const explicit = declaredDimension(input.declared);
  if (explicit) return { dimension: explicit, source: "declared" };

  const text = normalizedText(
    [input.stem, input.explanation, input.topic, input.focus].join(" "),
  );
  let best: CapabilityDimensionId = "foundations";
  let bestHits = 0;
  for (const dimension of CAPABILITY_DIMENSIONS) {
    const hits = dimension.keywords.reduce(
      (total, keyword) => total + (text.includes(normalizedText(keyword)) ? 1 : 0),
      0,
    );
    if (hits > bestHits) {
      best = dimension.id;
      bestHits = hits;
    }
  }
  return {
    dimension: best,
    source: bestHits > 0 ? "keyword" : "fallback",
  };
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  return [...new Set(values.map((value) => value?.trim()).filter(Boolean) as string[])];
}

function responseGrounding(response: AgentResponse | null | undefined) {
  const evidence = response?.rag_package?.evidence ?? [];
  const citations = response?.rag_package?.citations ?? [];
  return {
    sourceRefs: uniqueStrings([
      ...(response?.final_output?.evidence_refs ?? []),
      ...evidence.map((item) => item.source_file ?? item.source_doc),
      ...citations.map((item) => item.source_file ?? item.source_doc),
    ]),
    ragChunkIds: uniqueStrings([
      ...evidence.map((item) => item.chunk_id),
      ...citations.map((item) => item.chunk_id),
    ]),
  };
}

export function createQuizEvidence(
  attempt: QuizAttemptForAssessment,
): CapabilityEvidence[] {
  const grounding = responseGrounding(attempt.response);
  return attempt.questions.map((item, index) => {
    const question = item.question;
    const classification = classifyCapabilityDimensionWithSource({
      declared: question.capability_dimension,
      topic: attempt.topic,
      focus: attempt.focus,
      stem: question.stem,
      explanation: question.explanation,
    });
    const knowledgePoint =
      question.knowledge_point?.trim() || question.stem.trim().slice(0, 120);
    const questionSpecificSources = uniqueStrings(question.source_refs ?? []);
    const questionSpecificChunks = uniqueStrings(question.rag_chunk_ids ?? []);
    const questionGrounded =
      question.source_grounding_scope === "question" ||
      (question.source_grounding_scope === undefined &&
        (questionSpecificSources.length > 0 || questionSpecificChunks.length > 0));
    const possible =
      Number.isFinite(Number(item.possible)) && Number(item.possible) > 0
        ? Number(item.possible)
        : 1;
    const earned = Number.isFinite(Number(item.earned))
      ? Math.max(0, Math.min(possible, Number(item.earned)))
      : item.selectedAnswer === item.correctAnswer
        ? possible
        : 0;
    const correct =
      typeof item.isCorrect === "boolean"
        ? item.isCorrect
        : earned >= possible * 0.6;
    const subjective =
      question.question_type === "cloze" ||
      question.question_type === "short_answer";
    const graderConfidence =
      typeof item.graderConfidence === "number"
        ? Math.max(0, Math.min(1, item.graderConfidence))
        : null;
    return {
      id: item.questionId || `${attempt.attemptId}-q${index + 1}`,
      attemptId: attempt.attemptId,
      attemptNumber: Math.max(1, Math.trunc(attempt.attemptNumber || 1)),
      sourceType: "quiz",
      dimension: classification.dimension,
      dimensionSource: classification.source,
      topic: attempt.topic,
      knowledgePoint,
      knowledgePointId: normalizeKnowledgePointId(knowledgePoint),
      itemRevision: itemFingerprint(question),
      correct,
      earned,
      possible,
      difficulty: asDifficulty(question.difficulty || attempt.difficulty),
      occurredAt: attempt.occurredAt,
      sourceRefs: uniqueStrings([
        ...(question.source_refs ?? []),
        ...grounding.sourceRefs,
      ]),
      ragChunkIds: uniqueStrings([
        ...(question.rag_chunk_ids ?? []),
        ...grounding.ragChunkIds,
      ]),
      questionType: question.question_type,
      gradingMethod: item.gradingMethod,
      rubricVersion: item.rubricVersion,
      semanticScore: item.semanticScore,
      keyPointScore: item.keyPointScore,
      graderConfidence,
      questionGrounded,
      // Low-confidence AI grading remains in the audit trail, but it must not
      // change a formal capability rating until a reliable re-grade/review.
      reviewStatus:
        subjective && (graderConfidence === null || graderConfidence < 0.6)
          ? "pending_review"
          : "auto_verified",
      chapterId: attempt.chapterId,
      lectureId: attempt.lectureId,
      objectiveIds: uniqueStrings(attempt.objectiveIds ?? []),
      criticalSafetyError: item.criticalSafetyError === true,
    };
  });
}

export function mergeCapabilityEvidence(
  current: CapabilityEvidence[],
  incoming: CapabilityEvidence[],
): CapabilityEvidence[] {
  const byId = new Map<string, CapabilityEvidence>();
  for (const item of [...incoming, ...current]) {
    if (!byId.has(item.id)) byId.set(item.id, item);
  }
  return [...byId.values()]
    .sort(
      (a, b) =>
        new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime(),
    )
    .slice(0, 2_000);
}

export function normalizeCapabilityEvidence(value: unknown): CapabilityEvidence[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    if (!candidate || typeof candidate !== "object") return [];
    const item = candidate as Partial<CapabilityEvidence>;
    const dimension = declaredDimension(item.dimension);
    if (
      !dimension ||
      typeof item.id !== "string" ||
      typeof item.attemptId !== "string" ||
      typeof item.topic !== "string" ||
      typeof item.knowledgePoint !== "string" ||
      typeof item.correct !== "boolean" ||
      typeof item.occurredAt !== "string"
    ) {
      return [];
    }
    const earned = Number(item.earned);
    const possible = Number(item.possible);
    if (!Number.isFinite(earned) || !Number.isFinite(possible) || possible <= 0) {
      return [];
    }
    return [
      {
        id: item.id,
        attemptId: item.attemptId,
        attemptNumber: Math.max(1, Math.trunc(Number(item.attemptNumber) || 1)),
        sourceType:
          item.sourceType === "practice" ||
          item.sourceType === "external_assessment"
            ? item.sourceType
            : "quiz",
        dimension,
        dimensionSource:
          item.dimensionSource === "declared" ||
          item.dimensionSource === "keyword" ||
          item.dimensionSource === "fallback"
            ? item.dimensionSource
            : "fallback",
        topic: item.topic,
        knowledgePoint: item.knowledgePoint,
        knowledgePointId:
          typeof item.knowledgePointId === "string" && item.knowledgePointId
            ? item.knowledgePointId
            : normalizeKnowledgePointId(item.knowledgePoint),
        itemRevision:
          typeof item.itemRevision === "string" && item.itemRevision
            ? item.itemRevision
            : normalizeKnowledgePointId(item.knowledgePoint),
        correct: item.correct,
        earned,
        possible,
        difficulty: asDifficulty(item.difficulty),
        occurredAt: item.occurredAt,
        sourceRefs: Array.isArray(item.sourceRefs)
          ? uniqueStrings(
              item.sourceRefs.filter(
                (source): source is string => typeof source === "string",
              ),
            )
          : [],
        ragChunkIds: Array.isArray(item.ragChunkIds)
          ? uniqueStrings(
              item.ragChunkIds.filter(
                (chunk): chunk is string => typeof chunk === "string",
              ),
            )
          : [],
        questionType:
          typeof item.questionType === "string" ? item.questionType : undefined,
        gradingMethod:
          typeof item.gradingMethod === "string" ? item.gradingMethod : undefined,
        rubricVersion:
          typeof item.rubricVersion === "string" ? item.rubricVersion : undefined,
        semanticScore: Number.isFinite(Number(item.semanticScore))
          ? Number(item.semanticScore)
          : null,
        keyPointScore: Number.isFinite(Number(item.keyPointScore))
          ? Number(item.keyPointScore)
          : null,
        graderConfidence: Number.isFinite(Number(item.graderConfidence))
          ? Math.max(0, Math.min(1, Number(item.graderConfidence)))
          : null,
        questionGrounded: item.questionGrounded === true,
        reviewStatus:
          item.reviewStatus === "reviewed" || item.reviewStatus === "rejected"
            ? item.reviewStatus
            : item.sourceType === "practice" ||
                item.sourceType === "external_assessment"
              ? "pending_review"
              : "auto_verified",
        reviewedBy:
          typeof item.reviewedBy === "string" ? item.reviewedBy : undefined,
        lectureId:
          typeof item.lectureId === "string" ? item.lectureId : undefined,
        chapterId:
          typeof item.chapterId === "string" ? item.chapterId : undefined,
        objectiveIds: Array.isArray(item.objectiveIds)
          ? uniqueStrings(
              item.objectiveIds.filter(
                (objective): objective is string => typeof objective === "string",
              ),
            )
          : [],
        criticalSafetyError: item.criticalSafetyError === true,
      },
    ];
  });
}

function validEvidence(item: CapabilityEvidence): boolean {
  return (
    CAPABILITY_DIMENSIONS.some((dimension) => dimension.id === item.dimension) &&
    Number.isFinite(item.earned) &&
    Number.isFinite(item.possible) &&
    item.possible > 0 &&
    item.earned >= 0 &&
    item.earned <= item.possible
  );
}

function recencyWeight(occurredAt: string, now: Date): number {
  const timestamp = new Date(occurredAt).getTime();
  if (!Number.isFinite(timestamp)) return 1;
  const ageDays = Math.max(0, (now.getTime() - timestamp) / 86_400_000);
  // A 180-day half-life keeps old evidence while letting recent practice
  // reflect current ability more strongly.
  return Math.pow(0.5, ageDays / 180);
}

function masteryLabel(
  score: number | null,
  status: CapabilityRatingStatus,
): CapabilityDimensionResult["masteryLabel"] {
  if (score === null) return "待评估";
  if (status !== "rated") return "证据不足";
  if (score < 50) return "需巩固";
  if (score < 65) return "入门";
  if (score < 85) return "基本掌握";
  return "熟练";
}

function evidenceIsReviewed(item: CapabilityEvidence): boolean {
  if (item.reviewStatus === "rejected") return false;
  if (item.sourceType === "quiz") return item.reviewStatus !== "pending_review";
  if (item.sourceType === "external_assessment") {
    return item.reviewStatus === "reviewed" || item.reviewStatus === "auto_verified";
  }
  return item.reviewStatus === "reviewed";
}

/**
 * Keep the complete audit trail, but use only the first independent exposure
 * to the same item and at most one item per knowledge point in one attempt.
 */
export function effectiveCapabilityEvidence(
  evidence: CapabilityEvidence[],
): CapabilityEvidence[] {
  const sorted = [...evidence]
    .filter((item) => validEvidence(item) && evidenceIsReviewed(item))
    .sort(
      (a, b) =>
        new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime(),
    );
  const seenItems = new Set<string>();
  const seenAttemptKnowledge = new Set<string>();
  return sorted.filter((item) => {
    const fingerprint = `${item.dimension}|${item.itemRevision || item.id}`;
    const attemptKnowledge = `${item.attemptId}|${item.dimension}|${
      item.knowledgePointId || normalizeKnowledgePointId(item.knowledgePoint)
    }`;
    if (seenItems.has(fingerprint) || seenAttemptKnowledge.has(attemptKnowledge)) {
      return false;
    }
    seenItems.add(fingerprint);
    seenAttemptKnowledge.add(attemptKnowledge);
    return true;
  });
}

export function capabilityEvidenceWeight(
  item: CapabilityEvidence,
  now: Date,
): number {
  const graderReliability =
    typeof item.graderConfidence === "number"
      ? 0.35 + Math.max(0, Math.min(1, item.graderConfidence)) * 0.65
      : 1;
  return (
    DIFFICULTY_WEIGHT[item.difficulty] *
    recencyWeight(item.occurredAt, now) *
    SOURCE_RELIABILITY[item.sourceType] *
    DIMENSION_SOURCE_RELIABILITY[item.dimensionSource || "fallback"] *
    graderReliability
  );
}

type ScoreSlice = {
  score: number | null;
  observedScore: number | null;
  weightedAccuracy: number | null;
  effectiveWeight: number;
  confidence: number;
  status: CapabilityRatingStatus;
  knowledgePointCount: number;
  independentAttemptCount: number;
};

function calculateScoreSlice(
  items: CapabilityEvidence[],
  now: Date,
): ScoreSlice {
  if (!items.length) {
    return {
      score: null,
      observedScore: null,
      weightedAccuracy: null,
      effectiveWeight: 0,
      confidence: 0,
      status: "unassessed",
      knowledgePointCount: 0,
      independentAttemptCount: 0,
    };
  }
  let earnedWeight = 0;
  let possibleWeight = 0;
  for (const item of items) {
    const weight = capabilityEvidenceWeight(item, now);
    earnedWeight += (item.earned / item.possible) * weight;
    possibleWeight += weight;
  }
  const weightedAccuracy = possibleWeight
    ? Math.max(0, Math.min(1, earnedWeight / possibleWeight))
    : null;
  const estimated = weightedAccuracy === null
    ? null
    : (earnedWeight +
        CAPABILITY_RATING_POLICY.priorMean *
          CAPABILITY_RATING_POLICY.priorStrength) /
      (possibleWeight + CAPABILITY_RATING_POLICY.priorStrength);
  const knowledgePointCount = new Set(
    items.map((item) => item.knowledgePointId).filter(Boolean),
  ).size;
  const independentAttemptCount = new Set(items.map((item) => item.attemptId)).size;
  const groundedCount = items.filter((item) => item.questionGrounded).length;
  const volumeConfidence = Math.min(
    1,
    items.length / CAPABILITY_RATING_POLICY.evidenceForFullConfidence,
  );
  const diversityConfidence = Math.min(
    1,
    knowledgePointCount /
      CAPABILITY_RATING_POLICY.knowledgePointsForFullConfidence,
  );
  const attemptConfidence = Math.min(
    1,
    independentAttemptCount / CAPABILITY_RATING_POLICY.attemptsForFullConfidence,
  );
  const groundingConfidence = items.length ? groundedCount / items.length : 0;
  const confidence = Math.min(
    1,
    volumeConfidence * 0.45 +
      diversityConfidence * 0.25 +
      attemptConfidence * 0.2 +
      groundingConfidence * 0.1,
  );
  const rated =
    items.length >= CAPABILITY_RATING_POLICY.minimumEffectiveEvidence &&
    knowledgePointCount >= CAPABILITY_RATING_POLICY.minimumKnowledgePoints &&
    independentAttemptCount >=
      CAPABILITY_RATING_POLICY.minimumIndependentAttempts &&
    confidence >= CAPABILITY_RATING_POLICY.minimumConfidence;
  return {
    score: estimated === null ? null : Math.round(estimated * 100),
    observedScore:
      weightedAccuracy === null ? null : Math.round(weightedAccuracy * 100),
    weightedAccuracy,
    effectiveWeight: Number(possibleWeight.toFixed(2)),
    confidence: Number(confidence.toFixed(2)),
    status: rated ? "rated" : "insufficient",
    knowledgePointCount,
    independentAttemptCount,
  };
}

function confidenceLabel(
  evidenceCount: number,
  confidence: number,
): CapabilityDimensionResult["confidenceLabel"] {
  if (!evidenceCount) return "待评估";
  if (confidence >= 0.75) return "高";
  if (confidence >= 0.4) return "中";
  return "低";
}

export function calculateCapabilityAssessment(
  evidence: CapabilityEvidence[],
  now = new Date(),
): CapabilityAssessment {
  const accepted = evidence.filter(validEvidence);
  const effective = effectiveCapabilityEvidence(accepted);
  const entries = CAPABILITY_DIMENSIONS.map((definition) => {
    const rawItems = accepted.filter((item) => item.dimension === definition.id);
    const items = effective.filter((item) => item.dimension === definition.id);
    const overall = calculateScoreSlice(items, now);
    const knowledgeItems = items.filter(
      (item) => item.sourceType === "quiz" || item.sourceType === "external_assessment",
    );
    const practiceItems = items.filter(
      (item) => item.sourceType === "practice" || item.sourceType === "external_assessment",
    );
    const knowledge = calculateScoreSlice(knowledgeItems, now);
    const practice = calculateScoreSlice(practiceItems, now);
    const result: CapabilityDimensionResult = {
      ...definition,
      score: overall.score,
      observedScore: overall.observedScore,
      weightedAccuracy: overall.weightedAccuracy,
      evidenceCount: rawItems.length,
      effectiveEvidenceCount: items.length,
      knowledgePointCount: overall.knowledgePointCount,
      independentAttemptCount: overall.independentAttemptCount,
      effectiveWeight: overall.effectiveWeight,
      confidence: overall.confidence,
      confidenceLabel: confidenceLabel(items.length, overall.confidence),
      masteryLabel: masteryLabel(overall.score, overall.status),
      ratingStatus: overall.status,
      ratingReady: overall.status === "rated",
      knowledgeScore: knowledge.score,
      knowledgeObservedScore: knowledge.observedScore,
      knowledgeStatus: knowledge.status,
      knowledgeEvidenceCount: knowledgeItems.length,
      practiceScore: practice.score,
      practiceObservedScore: practice.observedScore,
      practiceStatus: practice.status,
      practiceEvidenceCount: practiceItems.filter(
        (item) => item.sourceType === "practice",
      ).length,
      externalEvidenceCount: practiceItems.filter(
        (item) => item.sourceType === "external_assessment",
      ).length,
      sourceCount: new Set(items.flatMap((item) => item.sourceRefs)).size,
      lastUpdated: rawItems.length
        ? [...rawItems].sort(
            (a, b) =>
              new Date(b.occurredAt).getTime() -
              new Date(a.occurredAt).getTime(),
          )[0].occurredAt
        : null,
    };
    return [definition.id, result] as const;
  });
  const dimensions = Object.fromEntries(entries) as Record<
    CapabilityDimensionId,
    CapabilityDimensionResult
  >;
  return {
    modelVersion: ASSESSMENT_MODEL_VERSION,
    dimensions,
    evidenceCount: accepted.length,
    effectiveEvidenceCount: effective.length,
    assessedDimensionCount: Object.values(dimensions).filter(
      (item) => item.evidenceCount > 0,
    ).length,
    ratedDimensionCount: Object.values(dimensions).filter(
      (item) => item.ratingReady,
    ).length,
  };
}

function averageRated(
  assessment: CapabilityAssessment,
  ids: CapabilityDimensionId[],
): number {
  const scores = ids
    .map((id) => assessment.dimensions[id])
    .filter((item) => item.ratingReady)
    .map((item) => item.score)
    .filter((score): score is number => score !== null);
  return scores.length
    ? scores.reduce((total, score) => total + score, 0) / scores.length
    : 0;
}

export function assessmentToScoreMap(
  assessment: CapabilityAssessment,
  _level: LearnerProfile["level"],
): ScoreMap {
  void _level;
  const scores = Object.fromEntries(
    CAPABILITY_DIMENSIONS.map((dimension) => [
      dimension.id,
      assessment.dimensions[dimension.id].ratingReady
        ? assessment.dimensions[dimension.id].score ?? 0
        : 0,
    ]),
  ) as ScoreMap;
  let weightedTotal = 0;
  let provisionalWeightedTotal = 0;
  for (const dimension of CAPABILITY_DIMENSIONS) {
    const result = assessment.dimensions[dimension.id];
    const weight = CNC_JOB_CAPABILITY_WEIGHTS[dimension.id];
    provisionalWeightedTotal += (result.score ?? 0) * (weight / 100);
    if (result.ratingReady) {
      weightedTotal += (result.score ?? 0) * (weight / 100);
    }
    scores[`${dimension.id}_assessed`] = result.ratingReady ? 1 : 0;
    scores[`${dimension.id}_confidence`] = Math.round(result.confidence * 100);
    scores[`${dimension.id}_provisional`] = result.score ?? 0;
  }

  // Legacy aliases keep the teammate's HTTP v1 profile metrics compatible.
  // They are derived values and are never editable in the UI.
  scores.theory = Math.round(
    averageRated(assessment, [
      "foundations",
      "process_planning",
      "quality_control",
    ]),
  );
  scores.safety = Math.round(
    assessment.dimensions.safety.ratingReady
      ? assessment.dimensions.safety.score ?? 0
      : 0,
  );
  scores.operation = Math.round(
    averageRated(assessment, [
      "machining_operation",
      "quality_control",
      "maintenance",
    ]),
  );
  scores.programming = Math.round(
    assessment.dimensions.programming.ratingReady
      ? assessment.dimensions.programming.score ?? 0
      : 0,
  );
  scores.overall = Math.round(weightedTotal);
  scores.provisional_overall = Math.round(provisionalWeightedTotal);
  scores.assessment_confidence = Math.round(
    (Object.values(assessment.dimensions).reduce(
      (total, item) => total + item.confidence,
      0,
    ) /
      CAPABILITY_DIMENSIONS.length) *
      100,
  );
  return scores;
}

export function capabilityResultList(
  assessment: CapabilityAssessment,
  _level: LearnerProfile["level"],
): CapabilityDimensionResult[] {
  void _level;
  // The v2 capability model always exposes the same eight axes. Missing data
  // is represented as zero by the profile-score normalizer, never by hiding
  // a dimension based on the learner's self-declared level.
  return CAPABILITY_DIMENSIONS.map(
    (dimension) => assessment.dimensions[dimension.id],
  );
}
