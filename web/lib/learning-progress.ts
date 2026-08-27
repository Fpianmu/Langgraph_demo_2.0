import type { LearnerProfile } from "@/lib/agent-contract";
import type {
  CapabilityAssessment,
  CapabilityDimensionId,
  CapabilityEvidence,
} from "./capability-assessment.ts";
import { CNC_JOB_CAPABILITY_WEIGHTS } from "./scoring-policy.ts";

export const LEARNING_PROGRESS_MODEL_VERSION = "cnc-job-readiness-v2";

export type LearningStageId = "l1" | "l2" | "l3" | "job_ready";

export type LearningProgressInputs = {
  assessment: CapabilityAssessment;
  capabilityEvidence?: CapabilityEvidence[];
  profile: LearnerProfile;
  chatQuestionCount: number;
  memoryEventCount: number;
  quizSessionCount: number;
  knowledgeGaps?: Array<Record<string, unknown>>;
  courseProgress?: Array<Record<string, unknown>>;
};

export type ProgressGate = {
  id: string;
  label: string;
  passed: boolean;
  current: string;
  requirement: string;
  blocking: boolean;
};

export type StageAssessment = {
  id: LearningStageId;
  label: string;
  roleOutcome: string;
  passed: boolean;
  completion: number;
  gates: ProgressGate[];
};

export type LearningProgressResult = {
  modelVersion: typeof LEARNING_PROGRESS_MODEL_VERSION;
  overallProgress: number;
  currentStageId: LearningStageId;
  currentStageLabel: string;
  currentStageOutcome: string;
  achievedStages: LearningStageId[];
  stages: StageAssessment[];
  gates: ProgressGate[];
  blockers: string[];
  nextActions: string[];
  theoryReadiness: number | null;
  practicalReadiness: number | null;
  weightedMastery: number;
  provisionalMastery: number;
  weightedConfidence: number;
  verifiedWeight: number;
  courseCompletion: number;
  currentChapterId: string;
  currentChapterTitle: string;
  evidence: {
    rawTraceCount: number;
    structuredEvidenceCount: number;
    effectiveEvidenceCount: number;
    assessedDimensionCount: number;
    ratedDimensionCount: number;
    quizEvidenceCount: number;
    practicalEvidenceCount: number;
    externalAssessmentCount: number;
    groundedEvidenceCount: number;
    openKnowledgeGapCount: number;
  };
  dimensions: Array<{
    id: CapabilityDimensionId;
    label: string;
    score: number | null;
    observedScore: number | null;
    ratingStatus: "unassessed" | "insufficient" | "rated";
    confidence: number;
    evidenceCount: number;
    effectiveEvidenceCount: number;
    knowledgeScore: number | null;
    knowledgeStatus: "unassessed" | "insufficient" | "rated";
    practiceScore: number | null;
    practiceStatus: "unassessed" | "insufficient" | "rated";
    practiceEvidenceCount: number;
    weight: number;
  }>;
  agentContext: Record<string, unknown>;
};

// The dimensions follow the CNC turning/milling and multi-axis occupational
// standards in /resource. Operation carries the largest single weight while
// safety remains a non-compensable gate.
export const JOB_READINESS_WEIGHTS = CNC_JOB_CAPABILITY_WEIGHTS;

const PROGRESS_DIMENSIONS: Array<{ id: CapabilityDimensionId; label: string }> = [
  { id: "safety", label: "安全规范" },
  { id: "foundations", label: "基础识图" },
  { id: "process_planning", label: "工艺规划" },
  { id: "programming", label: "数控编程" },
  { id: "machining_operation", label: "操作加工" },
  { id: "quality_control", label: "质量检测" },
  { id: "maintenance", label: "维护诊断" },
  { id: "advanced_manufacturing", label: "先进制造" },
];

export const COURSE_CHAPTERS = [
  ["1.1", "机床加工的基本概念"],
  ["1.2", "车床加工原理"],
  ["1.3", "常见加工方式与适用场景"],
  ["1.4", "工件测量与加工质量基础"],
  ["1.5", "理论学习与基础考核"],
  ["2.1", "车床系统与操作面板认知"],
  ["2.2", "基本操作流程与按键顺序"],
  ["2.3", "上机前准备与设备检查"],
  ["2.4", "加工过程中的安全注意事项"],
  ["2.5", "操作规范测试与上机资格确认"],
  ["3.1", "简单零件图纸识读"],
  ["3.2", "外圆加工训练"],
  ["3.3", "内孔加工训练"],
  ["3.4", "螺纹加工训练"],
  ["3.5", "单一加工特征的质量检查"],
  ["4.1", "多特征组合零件加工任务"],
  ["4.2", "按图纸完成工业性零件加工"],
  ["4.3", "尺寸检测与检验记录填写"],
  ["4.4", "加工结果评分与合格判定"],
  ["4.5", "不合格项目复训与重新考核"],
] as const;

export const COURSE_PHASES = [
  { id: "entry", label: "行业入门", range: "1.1–1.5", outcome: "理解机床、加工、测量与质量基础" },
  { id: "l1", label: "L1 规范上机", range: "2.1–2.5", outcome: "具备安全上机与规范操作基础" },
  { id: "l2", label: "L2 独立加工", range: "3.1–3.5", outcome: "可完成典型单特征零件加工与自检" },
  { id: "l3", label: "L3 岗位综合", range: "4.1–4.5", outcome: "可完成工业性综合任务并作质量判定" },
] as const;

function numeric(value: unknown): number {
  const result = Number(value);
  return Number.isFinite(result) ? result : 0;
}

function textFrom(record: Record<string, unknown>, keys: string[]): string {
  return keys.map((key) => String(record[key] ?? "")).join(" ").trim();
}

function isResolvedGap(gap: Record<string, unknown>): boolean {
  return /resolved|completed|closed|mastered|已解决|已掌握|完成/i.test(
    textFrom(gap, ["status", "state", "resolution"]),
  );
}

function isSafetyGap(gap: Record<string, unknown>): boolean {
  return /安全|急停|防护|违规|危险|safety/i.test(
    textFrom(gap, ["dimension", "topic", "knowledge_point", "description", "title"]),
  );
}

function verifiedAverageScores(
  assessment: CapabilityAssessment,
  ids: CapabilityDimensionId[],
  channel: "knowledge" | "practice",
): number | null {
  const values = ids
    .map((id) => {
      const result = assessment.dimensions[id];
      if (channel === "knowledge") {
        return result.knowledgeStatus === "rated" ? result.knowledgeScore : null;
      }
      return result.practiceStatus === "rated" ? result.practiceScore : null;
    })
    .filter((value): value is number => value !== null);
  return values.length
    ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
    : null;
}

function ratedChannelCount(
  assessment: CapabilityAssessment,
  ids: CapabilityDimensionId[],
  channel: "knowledge" | "practice",
): number {
  return ids.filter((id) => {
    const result = assessment.dimensions[id];
    return channel === "knowledge"
      ? result.knowledgeStatus === "rated"
      : result.practiceStatus === "rated";
  }).length;
}

function scoreGate(
  id: string,
  label: string,
  value: number | null,
  threshold: number,
  blocking = true,
): ProgressGate {
  return {
    id,
    label,
    passed: value !== null && value >= threshold,
    current: value === null ? "待评估" : `${value} 分`,
    requirement: `≥ ${threshold} 分`,
    blocking,
  };
}

function countGate(
  id: string,
  label: string,
  value: number,
  threshold: number,
  unit: string,
  blocking = true,
): ProgressGate {
  return {
    id,
    label,
    passed: value >= threshold,
    current: `${value} ${unit}`,
    requirement: `≥ ${threshold} ${unit}`,
    blocking,
  };
}

function stage(
  id: LearningStageId,
  label: string,
  roleOutcome: string,
  gates: ProgressGate[],
): StageAssessment {
  const passedCount = gates.filter((gate) => gate.passed).length;
  return {
    id,
    label,
    roleOutcome,
    passed: gates.every((gate) => !gate.blocking || gate.passed),
    completion: Math.round((passedCount / Math.max(1, gates.length)) * 100),
    gates,
  };
}

function courseState(rows: Array<Record<string, unknown>>) {
  const byChapter = new Map(rows.map((row) => [String(row.chapter_id ?? ""), row]));
  let totalCompletion = 0;
  let currentChapterId = "1.1";
  for (const [chapterId] of COURSE_CHAPTERS) {
    const row = byChapter.get(chapterId);
    if (!row) continue;
    const status = String(row.status ?? "");
    const completion = Math.max(0, Math.min(1, numeric(row.completion_rate)));
    totalCompletion += /completed|已完成/i.test(status) ? 1 : completion;
    if (/in_progress|needs_review|进行中|复训/i.test(status)) {
      currentChapterId = chapterId;
    }
  }
  if (!rows.some((row) => /in_progress|needs_review|进行中|复训/i.test(String(row.status ?? "")))) {
    const latest = rows.find((row) => String(row.chapter_id ?? ""));
    if (latest) currentChapterId = String(latest.chapter_id);
  }
  const title = COURSE_CHAPTERS.find(([id]) => id === currentChapterId)?.[1] ?? "课程起点";
  return {
    completion: Math.round((totalCompletion / COURSE_CHAPTERS.length) * 100),
    currentChapterId,
    currentChapterTitle: title,
  };
}

export function calculateLearningProgress(
  input: LearningProgressInputs,
): LearningProgressResult {
  const { assessment } = input;
  const evidence = assessment.evidenceCount;
  const effectiveEvidenceCount = assessment.effectiveEvidenceCount;
  const sourceEvidence = input.capabilityEvidence ?? [];
  const practicalEvidenceCount = sourceEvidence.filter(
    (item) =>
      item.sourceType === "practice" && item.reviewStatus === "reviewed",
  ).length;
  const externalAssessmentCount = sourceEvidence.filter(
    (item) =>
      item.sourceType === "external_assessment" &&
      item.reviewStatus === "reviewed",
  ).length;
  const quizEvidenceCount = sourceEvidence.filter(
    (item) => item.sourceType === "quiz",
  ).length;
  const groundedEvidenceCount = sourceEvidence.filter(
    (item) => item.questionGrounded,
  ).length;
  const openGaps = (input.knowledgeGaps ?? []).filter((gap) => !isResolvedGap(gap));
  const latestCriticalSafetyEvidence = sourceEvidence
    .filter(
      (item) =>
        item.dimension === "safety" &&
        item.criticalSafetyError === true &&
        item.reviewStatus !== "rejected",
    )
    .sort(
      (a, b) =>
        new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime(),
    )[0];
  const safetyRecoveryAttempts = latestCriticalSafetyEvidence
    ? new Set(
        sourceEvidence
          .filter(
            (item) =>
              item.dimension === "safety" &&
              item.criticalSafetyError !== true &&
              item.reviewStatus !== "pending_review" &&
              item.reviewStatus !== "rejected" &&
              item.possible > 0 &&
              item.earned / item.possible >= 0.8 &&
              new Date(item.occurredAt).getTime() >
                new Date(latestCriticalSafetyEvidence.occurredAt).getTime(),
          )
          .map((item) => item.attemptId),
      ).size
    : 0;
  const criticalSafetyGap =
    openGaps.some(isSafetyGap) ||
    (!!latestCriticalSafetyEvidence && safetyRecoveryAttempts < 2);
  const theoryDimensions: CapabilityDimensionId[] = [
    "foundations",
    "process_planning",
    "programming",
    "quality_control",
  ];
  const practicalDimensions: CapabilityDimensionId[] = [
    "machining_operation",
    "quality_control",
    "maintenance",
  ];
  const theoryReadiness = verifiedAverageScores(
    assessment,
    theoryDimensions,
    "knowledge",
  );
  const practicalReadiness = verifiedAverageScores(
    assessment,
    practicalDimensions,
    "practice",
  );
  const ratedTheoryDimensions = ratedChannelCount(
    assessment,
    theoryDimensions,
    "knowledge",
  );
  const ratedPracticalDimensions = ratedChannelCount(
    assessment,
    practicalDimensions,
    "practice",
  );
  const safetyKnowledgeScore =
    assessment.dimensions.safety.knowledgeStatus === "rated"
      ? assessment.dimensions.safety.knowledgeScore
      : null;
  const advancedKnowledgeScore =
    assessment.dimensions.advanced_manufacturing.knowledgeStatus === "rated"
      ? assessment.dimensions.advanced_manufacturing.knowledgeScore
      : null;

  let weightedMastery = 0;
  let provisionalMastery = 0;
  let weightedConfidence = 0;
  let verifiedWeight = 0;
  for (const dimension of PROGRESS_DIMENSIONS) {
    const result = assessment.dimensions[dimension.id];
    const weight = JOB_READINESS_WEIGHTS[dimension.id];
    provisionalMastery += (result.score ?? 0) * (weight / 100);
    if (result.ratingReady) {
      weightedMastery += (result.score ?? 0) * (weight / 100);
      verifiedWeight += weight;
    }
    weightedConfidence += result.confidence * weight;
  }
  weightedMastery = Math.round(weightedMastery);
  provisionalMastery = Math.round(provisionalMastery);
  weightedConfidence = Math.round(weightedConfidence);
  const course = courseState(input.courseProgress ?? []);

  const l1 = stage("l1", "L1 规范上机", "具备初级岗位所需的安全、理论与规范操作基础", [
    scoreGate("l1-safety", "安全知识评价", safetyKnowledgeScore, 60),
    scoreGate("l1-theory", "理论与工艺", theoryReadiness, 60),
    scoreGate("l1-practical", "已审核实操能力", practicalReadiness, 60),
    countGate("l1-theory-coverage", "可评级理论维度", ratedTheoryDimensions, 3, "维"),
    countGate("l1-practical-coverage", "可评级实操维度", ratedPracticalDimensions, 1, "维"),
    countGate("l1-dimensions", "可评级能力覆盖", assessment.ratedDimensionCount, 5, "维"),
    countGate("l1-evidence", "独立有效证据", effectiveEvidenceCount, 24, "条"),
    countGate("l1-practice-proof", "已审核实操证据", practicalEvidenceCount, 3, "条"),
  ]);
  const l2 = stage("l2", "L2 独立加工", "能够独立完成典型零件加工、检测与常见问题处理", [
    scoreGate("l2-safety", "安全知识评价", safetyKnowledgeScore, 70),
    scoreGate("l2-theory", "理论与工艺", theoryReadiness, 70),
    scoreGate("l2-practical", "已审核实操能力", practicalReadiness, 70),
    countGate("l2-theory-coverage", "可评级理论维度", ratedTheoryDimensions, 4, "维"),
    countGate("l2-practical-coverage", "可评级实操维度", ratedPracticalDimensions, 2, "维"),
    countGate("l2-dimensions", "可评级能力覆盖", assessment.ratedDimensionCount, 7, "维"),
    countGate("l2-evidence", "独立有效证据", effectiveEvidenceCount, 56, "条"),
    countGate("l2-practice-proof", "已审核实操证据", practicalEvidenceCount, 8, "条"),
  ]);
  const l3 = stage("l3", "L3 岗位综合", "能够完成工业性综合任务、质量判定与复杂问题分析", [
    scoreGate("l3-safety", "安全知识评价", safetyKnowledgeScore, 80),
    scoreGate("l3-theory", "理论与工艺", theoryReadiness, 80),
    scoreGate("l3-practical", "已审核实操能力", practicalReadiness, 80),
    scoreGate("l3-advanced", "先进制造知识", advancedKnowledgeScore, 70),
    countGate("l3-theory-coverage", "可评级理论维度", ratedTheoryDimensions, 4, "维"),
    countGate("l3-practical-coverage", "可评级实操维度", ratedPracticalDimensions, 3, "维"),
    countGate("l3-dimensions", "可评级能力覆盖", assessment.ratedDimensionCount, 8, "维"),
    countGate("l3-evidence", "独立有效证据", effectiveEvidenceCount, 96, "条"),
    countGate("l3-practice-proof", "已审核实操证据", practicalEvidenceCount, 16, "条"),
    countGate("l3-external-proof", "外部/教师考核", externalAssessmentCount, 1, "条"),
  ]);
  const jobReady = stage("job_ready", "岗位胜任", "达到项目内部就业准备标准，建议进入企业实岗复核", [
    { id: "job-l3", label: "L3 岗位综合", passed: l3.passed, current: l3.passed ? "已达标" : "未达标", requirement: "已达标", blocking: true },
    countGate("job-confidence", "评价可信度", weightedConfidence, 65, "%"),
    countGate("job-course", "课程完成度", course.completion, 90, "%"),
    { id: "job-safety-gap", label: "重大安全缺口", passed: !criticalSafetyGap, current: criticalSafetyGap ? "存在" : "未发现", requirement: "无未解决项", blocking: true },
  ]);
  const stages = [l1, l2, l3, jobReady];
  const achievedStages = stages.filter((item) => item.passed).map((item) => item.id);
  const current = stages.find((item) => !item.passed) ?? jobReady;
  const completedBefore = stages.findIndex((item) => item.id === current.id);
  const overallProgress = jobReady.passed
    ? 100
    : Math.min(99, Math.round(completedBefore * 25 + current.completion * 0.25));
  const blockers = current.gates
    .filter((gate) => gate.blocking && !gate.passed)
    .map((gate) => `${gate.label}：当前${gate.current}，要求${gate.requirement}`);
  const nextActions = blockers.slice(0, 3).map((item) => `优先补齐${item}`);
  if (!nextActions.length && openGaps.length) {
    nextActions.push("复习并关闭当前 Memory 中尚未解决的知识缺口");
  }

  const rawTraceCount =
    Math.max(0, input.chatQuestionCount) +
    Math.max(0, input.memoryEventCount) +
    Math.max(0, input.quizSessionCount) +
    practicalEvidenceCount +
    externalAssessmentCount;
  const dimensions = PROGRESS_DIMENSIONS.map((definition) => {
    const result = assessment.dimensions[definition.id];
    return {
      id: definition.id,
      label: definition.label,
      score: result.score,
      observedScore: result.observedScore,
      ratingStatus: result.ratingStatus,
      confidence: Math.round(result.confidence * 100),
      evidenceCount: result.evidenceCount,
      effectiveEvidenceCount: result.effectiveEvidenceCount,
      knowledgeScore: result.knowledgeScore,
      knowledgeStatus: result.knowledgeStatus,
      practiceScore: result.practiceScore,
      practiceStatus: result.practiceStatus,
      practiceEvidenceCount: result.practiceEvidenceCount,
      weight: JOB_READINESS_WEIGHTS[definition.id],
    };
  });
  const agentContext = {
    model_version: LEARNING_PROGRESS_MODEL_VERSION,
    evaluation_basis: "resource职业技能等级标准+考核大纲",
    current_stage: current.id,
    current_stage_label: current.label,
    overall_progress: overallProgress,
    weighted_mastery: weightedMastery,
    provisional_mastery: provisionalMastery,
    verified_weight: verifiedWeight,
    weighted_confidence: weightedConfidence,
    theory_readiness: theoryReadiness,
    practical_readiness: practicalReadiness,
    current_chapter_id: course.currentChapterId,
    current_chapter_title: course.currentChapterTitle,
    blockers,
    open_knowledge_gaps: openGaps.slice(0, 12),
    capability_dimensions: dimensions,
    learner_background: input.profile.background,
    learner_level_claim: input.profile.level,
    learner_preference: input.profile.preference,
    rules: [
      "学习者自述水平不直接增加能力得分",
      "安全门槛不可被其他能力补偿",
      "Quiz只能形成理论证据，就业准备必须包含实操与外部考核证据",
      "低样本或低置信维度只显示暂估，不参与岗位达标",
    ],
  };

  return {
    modelVersion: LEARNING_PROGRESS_MODEL_VERSION,
    overallProgress,
    currentStageId: current.id,
    currentStageLabel: current.label,
    currentStageOutcome: current.roleOutcome,
    achievedStages,
    stages,
    gates: current.gates,
    blockers,
    nextActions,
    theoryReadiness,
    practicalReadiness,
    weightedMastery,
    provisionalMastery,
    weightedConfidence,
    verifiedWeight,
    courseCompletion: course.completion,
    currentChapterId: course.currentChapterId,
    currentChapterTitle: course.currentChapterTitle,
    evidence: {
      rawTraceCount,
      structuredEvidenceCount: evidence,
      effectiveEvidenceCount,
      assessedDimensionCount: assessment.assessedDimensionCount,
      ratedDimensionCount: assessment.ratedDimensionCount,
      quizEvidenceCount,
      practicalEvidenceCount,
      externalAssessmentCount,
      groundedEvidenceCount,
      openKnowledgeGapCount: openGaps.length,
    },
    dimensions,
    agentContext,
  };
}
