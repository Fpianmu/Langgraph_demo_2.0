"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type {
  AgentRequest,
  AgentResponse,
  AgentTrace,
  LearnerProfile,
  ProfilePatch,
  QuizQuestion,
  ScoreMap,
} from "@/lib/agent-contract";
import {
  buildAgentRequest,
  dispatchToCentralOrchestrator,
} from "@/lib/orchestrator-client";
import type {
  AgentActivityEvent,
  AgentMessageEvent,
  GraphPayloadRefs,
  GraphRunEvent,
  GraphRunStatus,
} from "@/lib/graph-run-client";
import {
  checkBackendHealth,
  mergeBackendProfile,
  saveBackendProfile,
} from "@/lib/profile-client";
import {
  loadBackendWorkspaceState,
  saveBackendWorkspaceState,
  type FrontendStateSnapshot,
} from "@/lib/workspace-state-client";
import {
  buildLearningRecommendations,
  type LearningRecommendations,
} from "@/lib/learning-recommendations";
import {
  DEFAULT_USER_IDENTITY,
  isProvidedAvatar,
  UserAvatar,
  UserProfileControl,
  type UserIdentity,
} from "@/components/UserIdentity";
import { MarkdownContent } from "@/components/MarkdownContent";
import { UserCenterView } from "@/components/UserCenterView";
import { UserAccessDialog } from "@/components/UserAccessDialog";
import { listUsers, type UserSummary } from "@/lib/user-client";
import {
  loadUserLearningPath,
  type LearningPathChapter,
  type UserLearningPath,
} from "@/lib/learning-path-client";
import {
  loadCapabilityScores,
  type CapabilityScoresState,
} from "@/lib/capability-score-client";
import {
  loadBackendKnowledgeGaps,
  normalizeKnowledgeGapItems,
  type KnowledgeGapState,
} from "@/lib/knowledge-gap-client";
import {
  ASSESSMENT_MODEL_VERSION,
  assessmentToScoreMap,
  calculateCapabilityAssessment,
  capabilityResultList,
  createQuizEvidence,
  mergeCapabilityEvidence,
  normalizeCapabilityEvidence,
  type CapabilityAssessment,
  type CapabilityEvidence,
} from "@/lib/capability-assessment";
import {
  isSubjectiveQuizQuestion,
  createQuizSession,
  normalizeQuizSessions,
  normalizeTrueFalseQuestion,
  quizAnswerKey,
  quizExplanationText,
  quizQuestionPoints,
  quizQuestionType,
  quizSessionProgress,
  setQuizCurrentIndex,
  setQuizExplanationMode,
  submitQuizAnswer,
  updateQuizDraft,
  upsertQuizSession,
  type QuizSession,
} from "@/lib/quiz-session";
import { gradeSubjectiveQuizAnswer } from "@/lib/quiz-grading-client";
import {
  submitPersistedQuizAttempts,
  syncQuizProfileEvidence,
} from "@/lib/quiz-persistence-client";
import {
  batchQuizBlueprint,
  createQuizBlueprint,
  DEFAULT_QUIZ_QUESTION_COUNT,
  MAX_QUIZ_QUESTION_COUNT,
  MIN_QUIZ_QUESTION_COUNT,
  normalizeQuizCount,
  QUIZ_DIFFICULTY_LABELS,
  QUIZ_TYPE_LABELS,
  summarizeQuizBlueprint,
  type QuizBlueprintItem,
  type QuizQuestionType,
} from "@/lib/quiz-blueprint";
import {
  COURSE_PHASES,
  calculateLearningProgress,
  type LearningProgressResult,
  type ProgressGate,
} from "@/lib/learning-progress";
import {
  calculateLectureMastery,
  createLectureSession,
  nextCourseChapter,
  normalizeLectureSessions,
  upsertLectureSession,
  type LectureGenerationReason,
  type LectureSession,
} from "@/lib/lecture-session";

type View = "chat" | "quiz" | "lecture" | "memory" | "progress";
type ConnectionState = "idle" | "checking" | "live" | "needs-key";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  followUps?: string[];
};

type MemoryEvent = {
  id: string;
  title: string;
  detail: string;
  time: string;
};

type PendingSuggestion = {
  id: string;
  kind: "profile";
  patch: ProfilePatch;
};

type LocalWorkspaceCache = {
  profile?: LearnerProfile;
  scores?: ScoreMap;
  frontendState?: Partial<FrontendStateSnapshot>;
};

const DEFAULT_PROFILE: LearnerProfile = {
  background: "非机械专业",
  level: "beginner",
  preference: "步骤化、少术语",
};

const EMPTY_CAPABILITY_ASSESSMENT = calculateCapabilityAssessment([]);
const DEFAULT_SCORES: ScoreMap = assessmentToScoreMap(
  EMPTY_CAPABILITY_ASSESSMENT,
  "beginner",
);

const ACTIVE_COURSE_ID = "cnc_lathe";
const ACTIVE_CHAPTER_ID = "1.1";
const QA_CONTEXT_VERSION = "cnc-domain-v2";
const SIDEBAR_PREFERENCE_KEY = "zlink-sidebar-collapsed-v1";
const CHAT_HISTORY_PANEL_PREFERENCE_KEY = "zlink-chat-history-panel-collapsed-v1";
const MEMORY_LOG_PANEL_PREFERENCE_KEY = "zlink-memory-log-panel-collapsed-v1";
const QUIZ_CONFIG_PANEL_PREFERENCE_KEY = "zlink-quiz-config-panel-collapsed-v1";
const ACTIVE_USER_PREFERENCE_KEY = "zlink-active-user-id-v1";
const WORKSPACE_CACHE_PREFIX = "knowledge-chain-memory-v1";

const TRACE_LABELS: Record<string, string> = {
  input_normalizer: "输入规范化",
  input_router: "输入理解与路由",
  rag_query_builder: "构造检索问题",
  rag_agent: "领域知识检索",
  rag_node: "领域知识检索",
  generation_router: "生成任务分发",
  content_builder_agent: "内容生成",
  qa_answer_generator: "问答生成",
  question_generator: "Quiz 生成",
  lecture_generator: "讲义生成",
  practice_guide_generator: "实训资料生成",
  content_check_agent: "依据性审查",
  safety_review_agent: "安全审查",
  personalization_agent: "个性化处理",
  personalization_node: "个性化处理与归档",
  learning_status_router: "学情任务路由",
  feedback_node: "学情反馈与画像更新",
  progress_advance_node: "学习进度推进",
};

const AGENT_LABELS: Record<string, string> = {
  task_dispatch: "任务调度 Agent",
  knowledge_generation: "知识检索与生成 Agent",
  learning_management: "学情管理 Agent",
  personalized_generation: "个性化生成 Agent",
  hallucination_elimination: "幻觉消除 Agent",
  practice_evaluation: "实训评估 Agent",
};

const RUN_STATUS_LABELS: Record<GraphRunStatus, string> = {
  idle: "等待任务",
  created: "任务已创建",
  running: "协作运行中",
  completed: "运行已完成",
  failed: "运行失败",
  cancelled: "运行已取消",
};

const PAYLOAD_REF_LABELS: Record<string, string> = {
  route_decision: "路由决策",
  evidence_count: "检索证据",
  claim_count: "待核声明",
  artifact_paths: "生成产物",
  verification_decision: "校验结论",
  profile_update_summary: "画像更新",
};

const PENDING_TRACE: AgentTrace[] = [
  {
    node: "input_normalizer",
    status: "success",
    summary: "已接收任务与用户画像",
  },
  {
    node: "rag_agent",
    status: "running",
    summary: "中央调度器正在组织 Agent 协作",
  },
  {
    node: "content_builder_agent",
    status: "queued",
    summary: "等待上一步结果",
  },
  {
    node: "content_check_agent",
    status: "queued",
    summary: "等待内容生成",
  },
];

const INITIAL_MESSAGE: ChatMessage = {
  id: "welcome-message",
  role: "assistant",
  content:
    "Hello，我是知链。你可以直接提问，也可以让我根据当前Memory生成个性化解释和测验",
};

function uid(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
  }
  return `${prefix}-${Date.now().toString(36)}`;
}

function learningMaterialLabel(materialType: string): string {
  const labels: Record<string, string> = {
    lecture: "学习讲义",
    quiz: "Quiz 测评",
    practice: "实训练习",
    simulation: "仿真训练",
    qa: "问答辅导",
  };
  return labels[materialType] || materialType;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function workspaceCacheKey(userId: string): string {
  return `${WORKSPACE_CACHE_PREFIX}:${userId}`;
}

function readLocalWorkspaceCache(userId: string): LocalWorkspaceCache | null {
  try {
    const raw =
      window.localStorage.getItem(workspaceCacheKey(userId)) ||
      (userId === "user_001"
        ? window.localStorage.getItem(WORKSPACE_CACHE_PREFIX)
        : null);
    const root = raw ? asRecord(JSON.parse(raw)) : null;
    if (!root) return null;

    const embedded = asRecord(root.frontendState);
    const legacyIdentity = asRecord(root.userIdentity);
    const frontendState = (embedded || {
      state_version: 1,
      qa_context_version: root.qaContextVersion,
      messages: root.messages,
      history: root.history,
      memory_events: root.memoryEvents,
      pending_suggestions: root.pendingSuggestions,
      user_identity: legacyIdentity,
      qa_session_id: root.qaSessionId,
    }) as Partial<FrontendStateSnapshot>;

    return {
      profile: asRecord(root.profile) as LearnerProfile | undefined,
      scores: asRecord(root.scores) as ScoreMap | undefined,
      frontendState,
    };
  } catch {
    return null;
  }
}

function normalizeFrontendState(snapshot: Partial<FrontendStateSnapshot>) {
  const messages = Array.isArray(snapshot.messages)
    ? snapshot.messages
        .map((item) => asRecord(item))
        .filter(
          (item): item is Record<string, unknown> =>
            !!item &&
            typeof item.id === "string" &&
            (item.role === "user" || item.role === "assistant") &&
            typeof item.content === "string",
        )
        .map((item) => ({
          id: item.id as string,
          role: item.role as "user" | "assistant",
          content: item.content as string,
          ...(Array.isArray(item.followUps)
            ? {
                followUps: item.followUps.filter(
                  (value): value is string => typeof value === "string",
                ),
              }
            : {}),
        }))
    : undefined;
  const memoryEvents = Array.isArray(snapshot.memory_events)
    ? snapshot.memory_events
        .map((item) => asRecord(item))
        .filter(
          (item): item is Record<string, unknown> =>
            !!item &&
            typeof item.id === "string" &&
            typeof item.title === "string" &&
            typeof item.detail === "string" &&
            typeof item.time === "string",
        )
        .map((item) => ({
          id: item.id as string,
          title: item.title as string,
          detail: item.detail as string,
          time: item.time as string,
        }))
    : undefined;
  const identity = asRecord(snapshot.user_identity);
  const userIdentity =
    identity &&
    typeof identity.nickname === "string" &&
    identity.nickname.trim() &&
    typeof identity.avatarId === "string" &&
    isProvidedAvatar(identity.avatarId)
      ? {
          nickname: identity.nickname.trim().slice(0, 20),
          avatarId: identity.avatarId,
        }
      : undefined;
  const pendingSuggestions = Array.isArray(snapshot.pending_suggestions)
    ? snapshot.pending_suggestions.filter((item): item is PendingSuggestion => {
        const record = asRecord(item);
        return (
          !!record &&
          typeof record.id === "string" &&
          record.kind === "profile" &&
          !!asRecord(record.patch)
        );
      })
    : undefined;

  return {
    messages,
    history: Array.isArray(snapshot.history)
      ? snapshot.history.filter(
          (item): item is string => typeof item === "string" && !!item.trim(),
        )
      : undefined,
    memoryEvents,
    pendingSuggestions,
    userIdentity,
    qaSessionId:
      snapshot.qa_context_version === QA_CONTEXT_VERSION &&
      typeof snapshot.qa_session_id === "string"
        ? snapshot.qa_session_id
        : "",
    capabilityEvidence: asRecord(snapshot.capability_assessment)
      ? normalizeCapabilityEvidence(
          asRecord(snapshot.capability_assessment)?.evidence,
        )
      : undefined,
    quizSessions: Array.isArray(snapshot.quiz_sessions)
      ? normalizeQuizSessions(snapshot.quiz_sessions)
      : undefined,
    activeQuizSessionId:
      typeof snapshot.active_quiz_session_id === "string"
        ? snapshot.active_quiz_session_id
        : "",
    lectureSessions: Array.isArray(snapshot.lecture_sessions)
      ? normalizeLectureSessions(snapshot.lecture_sessions)
      : undefined,
    activeLectureSessionId:
      typeof snapshot.active_lecture_session_id === "string"
        ? snapshot.active_lecture_session_id
        : "",
  };
}

function materialCandidates(
  response: AgentResponse,
  kind: "qa" | "quiz",
): Record<string, unknown>[] {
  const root = asRecord(response);
  const finalOutput = asRecord(root?.final_output);
  const finalMaterials = asRecord(root?.final_materials);
  const nestedMaterials = asRecord(finalOutput?.materials);
  const specificKeys =
    kind === "qa"
      ? ["personalized_qa_output", "final_qa_output"]
      : ["final_question_output", "personalized_question_output"];

  return [
    ...specificKeys.map((key) => root?.[key]),
    finalOutput,
    nestedMaterials?.[kind],
    finalMaterials?.[kind],
  ]
    .map(asRecord)
    .filter(
      (item): item is Record<string, unknown> =>
        !!item && !isRejectedAgentMaterial(item),
    );
}

function isRejectedAgentMaterial(material: Record<string, unknown>): boolean {
  const meta = asRecord(material.meta);
  const statuses = [meta?.status, meta?.verification_status]
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim().toLowerCase());
  return statuses.some((status) =>
    ["rejected", "validation_error", "failed", "error"].includes(status),
  );
}

function assertSuccessfulAgentResponse(
  response: AgentResponse,
  materialLabel: string,
) {
  if (response.status === "success") return;
  const reason =
    typeof response.check_report?.summary === "string"
      ? response.check_report.summary.trim()
      : "";
  throw new Error(
    reason ||
      `中央调度器未返回可用${materialLabel}（状态：${response.status || "unknown"}）`,
  );
}

function asQaPayload(response: AgentResponse) {
  for (const output of materialCandidates(response, "qa")) {
    const payload = asRecord(output.payload) || output;
    const answer = payload.answer;
    if (typeof answer !== "string" || !answer.trim()) continue;
    const followUps = Array.isArray(payload.follow_ups)
      ? payload.follow_ups.filter(
          (item): item is string => typeof item === "string" && !!item.trim(),
        )
      : undefined;
    return {
      question: typeof payload.question === "string" ? payload.question : undefined,
      answer,
      follow_ups: followUps,
    };
  }
  return null;
}

function asQuizQuestions(response: AgentResponse): QuizQuestion[] {
  for (const output of materialCandidates(response, "quiz")) {
    const payload = asRecord(output.payload) || output;
    const questions = payload.questions;
    if (!Array.isArray(questions)) continue;
    const validQuestions = questions.filter(
      (question): question is QuizQuestion =>
        !!question &&
        typeof question === "object" &&
        typeof (question as QuizQuestion).stem === "string" &&
        (Array.isArray((question as QuizQuestion).options) ||
          ["cloze", "short_answer"].includes(
            String((question as QuizQuestion).question_type),
          )),
    );
    if (validQuestions.length) return validQuestions;
  }
  return [];
}

function applyBlueprintToQuestion(
  question: QuizQuestion,
  slot: QuizBlueprintItem,
): QuizQuestion {
  const questionType = slot.questionType;
  const options = Array.isArray(question.options) ? question.options : [];
  const rawQuestion = asRecord(question);
  const rawKnowledgePoints = Array.isArray(rawQuestion?.knowledge_points)
    ? rawQuestion.knowledge_points
    : [];
  const firstKnowledgePoint = rawKnowledgePoints[0];
  const knowledgePointRecord = asRecord(firstKnowledgePoint);
  const knowledgePoint =
    (typeof question.knowledge_point === "string" && question.knowledge_point.trim()) ||
    (typeof firstKnowledgePoint === "string" && firstKnowledgePoint.trim()) ||
    String(knowledgePointRecord?.name || knowledgePointRecord?.id || "").trim();
  const normalized = normalizeTrueFalseQuestion({
    ...question,
    question_type: questionType,
    options:
      questionType === "cloze" || questionType === "short_answer"
          ? []
          : options,
    reference_answer: question.reference_answer || question.answer,
    concise_explanation: question.concise_explanation,
    detailed_explanation: question.detailed_explanation,
    difficulty: slot.difficulty,
    points: slot.points,
    capability_dimension: slot.capabilityDimension,
    knowledge_point: knowledgePoint || undefined,
  });
  if (questionType === "true_false" && !normalized.answer) {
    throw new Error(
      `第 ${slot.sequence} 题的判断题答案无法识别，中央调度器必须返回 A/B、正确/错误或 true/false`,
    );
  }
  return normalized;
}

function mergeQuizResponses(
  responses: AgentResponse[],
  questions: QuizQuestion[],
): AgentResponse {
  const latest = responses.at(-1)!;
  const evidence = responses.flatMap((response) => response.rag_package?.evidence ?? []);
  const citations = responses.flatMap((response) => response.rag_package?.citations ?? []);
  return {
    ...latest,
    final_output: {
      ...(latest.final_output || {}),
      payload: { questions },
      evidence_refs: [
        ...new Set(responses.flatMap((response) => response.final_output?.evidence_refs ?? [])),
      ],
    },
    rag_package: {
      ...(latest.rag_package || {}),
      evidence,
      citations,
      confidence: responses.length
        ? responses.reduce(
            (sum, response) => sum + Number(response.rag_package?.confidence || 0),
            0,
          ) / responses.length
        : 0,
    },
    agent_trace: responses.flatMap((response) => response.agent_trace || []),
  };
}

function assessmentEvidenceForSession(
  session: QuizSession,
  onlyQuestionId?: string,
): CapabilityEvidence[] {
  return session.questions.flatMap((question) => {
    if (onlyQuestionId && question.id !== onlyQuestionId) return [];
    const response = session.responses[question.id];
    if (!response?.submittedAt) return [];
    return createQuizEvidence({
      attemptId: session.id,
      attemptNumber: 1,
      topic: session.topic,
      focus: session.focus,
      difficulty: session.difficulty,
      occurredAt: response.submittedAt,
      chapterId: session.assessmentLink?.chapterId || session.chapterId,
      lectureId: session.assessmentLink?.lectureId,
      objectiveIds: session.assessmentLink?.objectiveIds,
      questions: [
        {
          questionId: question.id,
          question,
          selectedAnswer: response.selectedAnswer,
          correctAnswer: quizAnswerKey(question),
          earned: response.earnedPoints ?? undefined,
          possible: response.possiblePoints,
          isCorrect: response.isCorrect ?? undefined,
          gradingMethod: response.gradingMethod,
          rubricVersion: response.rubricVersion,
          semanticScore: response.semanticSimilarity,
          keyPointScore: response.keyPointCoverage,
          graderConfidence: response.graderConfidence,
          criticalSafetyError: response.safetyCriticalError,
        },
      ],
    });
  });
}

function capabilityEvidenceSyncKey(
  userId: string,
  evidence: CapabilityEvidence[],
): string {
  return `${userId}:${evidence
    .filter((item) => item.sourceType === "quiz")
    .map((item) => `${item.id}:${item.reviewStatus}:${item.earned}/${item.possible}`)
    .sort()
    .join("|")}`;
}

function connectionText(state: ConnectionState): string {
  if (state === "checking") return "正在连接中央调度器";
  if (state === "live") return "中央调度器已连接";
  if (state === "needs-key") return "后端已连接 · 模型密钥未配置";
  return "中央调度器待验证";
}

function SidebarToggleButton({
  collapsed,
  onToggle,
  className = "",
}: {
  collapsed: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const label = collapsed ? "展开边栏" : "隐藏边栏";
  return (
    <button
      type="button"
      className={`sidebar-toggle ${className}`.trim()}
      aria-controls="zlink-sidebar"
      aria-expanded={!collapsed}
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      <span className="sidebar-toggle-icon" aria-hidden="true" />
    </button>
  );
}

export default function LearningWorkspace() {
  const [activeView, setActiveView] = useState<View>("progress");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarPreferenceReady, setSidebarPreferenceReady] = useState(false);
  const [moreInfoOpen, setMoreInfoOpen] = useState(false);
  const [profile, setProfile] = useState<LearnerProfile>(DEFAULT_PROFILE);
  const [capabilityEvidence, setCapabilityEvidence] = useState<
    CapabilityEvidence[]
  >([]);
  const [quizSessions, setQuizSessions] = useState<QuizSession[]>([]);
  const [activeQuizSessionId, setActiveQuizSessionId] = useState("");
  const [lectureSessions, setLectureSessions] = useState<LectureSession[]>([]);
  const [activeLectureSessionId, setActiveLectureSessionId] = useState("");
  const [backendKnowledgeGaps, setBackendKnowledgeGaps] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [backendCourseProgress, setBackendCourseProgress] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [backendCapabilityScores, setBackendCapabilityScores] =
    useState<CapabilityScoresState | null>(null);
  const [backendKnowledgeGapState, setBackendKnowledgeGapState] =
    useState<KnowledgeGapState | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([INITIAL_MESSAGE]);
  const [history, setHistory] = useState<string[]>([]);
  const [memoryEvents, setMemoryEvents] = useState<MemoryEvent[]>([
    {
      id: "initial-memory",
      title: "初始画像已建立",
      detail: "已记录学习背景、当前水平和表达偏好。",
      time: "当前设备",
    },
  ]);
  const [pendingSuggestions, setPendingSuggestions] = useState<
    PendingSuggestion[]
  >([]);
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [busy, setBusy] = useState(false);
  const [trace, setTrace] = useState<AgentTrace[]>([]);
  const [graphEvents, setGraphEvents] = useState<GraphRunEvent[]>([]);
  const [activeRunId, setActiveRunId] = useState("");
  const [graphRunStatus, setGraphRunStatus] = useState<GraphRunStatus>("idle");
  const [lastResponse, setLastResponse] = useState<AgentResponse | null>(null);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
    null,
  );
  const [userIdentity, setUserIdentity] = useState<UserIdentity>(
    DEFAULT_USER_IDENTITY,
  );
  const [qaSessionId, setQaSessionId] = useState("");
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [activeUserId, setActiveUserId] = useState("");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [userDialog, setUserDialog] = useState<"switch" | "create" | null>(null);
  const [userLearningPath, setUserLearningPath] = useState<UserLearningPath | null>(null);
  const [learningPathLoading, setLearningPathLoading] = useState(false);
  const [learningPathError, setLearningPathError] = useState("");
  const persistenceRevision = useRef(0);
  const profileEvidenceSyncKey = useRef("");

  useEffect(() => {
    try {
      // Restoring a device-local layout preference requires one client-only update.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSidebarCollapsed(
        window.localStorage.getItem(SIDEBAR_PREFERENCE_KEY) === "true",
      );
    } catch {
      // Keep the sidebar open if browser preferences are unavailable.
    } finally {
      setSidebarPreferenceReady(true);
    }
  }, []);

  useEffect(() => {
    if (!sidebarPreferenceReady) return;
    try {
      window.localStorage.setItem(
        SIDEBAR_PREFERENCE_KEY,
        String(sidebarCollapsed),
      );
    } catch {
      // The preference is optional and must not block the learning workspace.
    }
  }, [sidebarCollapsed, sidebarPreferenceReady]);

  const localCapabilityAssessment = useMemo(
    () => calculateCapabilityAssessment(capabilityEvidence),
    [capabilityEvidence],
  );
  const activeBackendCapabilityScores =
    backendCapabilityScores?.userId === activeUserId
      ? backendCapabilityScores
      : null;
  const capabilityAssessment =
    activeBackendCapabilityScores?.assessment ?? localCapabilityAssessment;
  const effectiveCapabilityEvidence =
    activeBackendCapabilityScores?.evidence ?? capabilityEvidence;
  const activeKnowledgeGapState =
    backendKnowledgeGapState?.userId === activeUserId
      ? backendKnowledgeGapState
      : null;
  const effectiveKnowledgeGaps = useMemo(
    () =>
      activeKnowledgeGapState?.knowledgeGaps ??
      normalizeKnowledgeGapItems(backendKnowledgeGaps),
    [activeKnowledgeGapState?.knowledgeGaps, backendKnowledgeGaps],
  );
  const progressKnowledgeGaps = useMemo(
    () =>
      effectiveKnowledgeGaps.map((gap) => ({
        gap_id: gap.id,
        status: gap.status,
        dimension: gap.category,
        topic: gap.concept,
        knowledge_point: gap.knowledgePointId,
        description: gap.evidence,
        title: gap.concept,
        severity: gap.severity,
      })),
    [effectiveKnowledgeGaps],
  );
  const scores = useMemo(
    () =>
      activeBackendCapabilityScores?.scores ??
      assessmentToScoreMap(localCapabilityAssessment, profile.level),
    [activeBackendCapabilityScores?.scores, localCapabilityAssessment, profile.level],
  );
  const learningProgress = useMemo(
    () =>
      calculateLearningProgress({
        assessment: capabilityAssessment,
        capabilityProfileScore: activeBackendCapabilityScores?.profileScore,
        capabilityEvidence: effectiveCapabilityEvidence,
        profile,
        chatQuestionCount: messages.filter((message) => message.role === "user").length,
        memoryEventCount: memoryEvents.length,
        quizSessionCount: quizSessions.length,
        knowledgeGaps: progressKnowledgeGaps,
        courseProgress: backendCourseProgress,
      }),
    [
      backendCourseProgress,
      progressKnowledgeGaps,
      activeBackendCapabilityScores?.profileScore,
      capabilityAssessment,
      effectiveCapabilityEvidence,
      memoryEvents.length,
      messages,
      profile,
      quizSessions.length,
    ],
  );

  const applyFrontendState = useCallback(
    (snapshot: Partial<FrontendStateSnapshot>) => {
      const restored = normalizeFrontendState(snapshot);
      if (restored.messages) {
        setMessages(restored.messages.length ? restored.messages : [INITIAL_MESSAGE]);
      }
      if (restored.history) setHistory(restored.history);
      if (restored.memoryEvents) setMemoryEvents(restored.memoryEvents);
      if (restored.pendingSuggestions) {
        setPendingSuggestions(restored.pendingSuggestions);
      }
      if (restored.userIdentity) setUserIdentity(restored.userIdentity);
      if (restored.capabilityEvidence) {
        setCapabilityEvidence(restored.capabilityEvidence);
      }
      if (restored.quizSessions) {
        setQuizSessions(restored.quizSessions);
        setActiveQuizSessionId(
          restored.quizSessions.some(
            (session) => session.id === restored.activeQuizSessionId,
          )
            ? restored.activeQuizSessionId
            : restored.quizSessions[0]?.id || "",
        );
      }
      if (restored.lectureSessions) {
        setLectureSessions(restored.lectureSessions);
        setActiveLectureSessionId(
          restored.lectureSessions.some(
            (session) => session.id === restored.activeLectureSessionId,
          )
            ? restored.activeLectureSessionId
            : restored.lectureSessions[0]?.id || "",
        );
      }
      setQaSessionId(restored.qaSessionId);
    },
    [],
  );

  const learningRecommendations = useMemo(
    () =>
      buildLearningRecommendations({
        profile,
        scores,
        memoryEvents,
        // The field is usually null before RAG is connected. Keeping it in
        // the same calculation means future retrieved evidence immediately
        // influences recommendations without replacing the UI again.
        ragPackage: lastResponse?.rag_package,
      }),
    [lastResponse?.rag_package, memoryEvents, profile, scores],
  );

  const resetWorkspace = useCallback((user?: UserSummary) => {
    setProfile({
      ...DEFAULT_PROFILE,
      background: user?.background_type || DEFAULT_PROFILE.background,
    });
    setCapabilityEvidence([]);
    setQuizSessions([]);
    setActiveQuizSessionId("");
    setLectureSessions([]);
    setActiveLectureSessionId("");
    setBackendKnowledgeGaps([]);
    setBackendCourseProgress([]);
    setBackendCapabilityScores(null);
    setBackendKnowledgeGapState(null);
    setMessages([INITIAL_MESSAGE]);
    setHistory([]);
    setMemoryEvents([
      {
        id: "initial-memory",
        title: "初始画像已建立",
        detail: "已记录学习背景、当前水平和表达偏好。",
        time: "当前设备",
      },
    ]);
    setPendingSuggestions([]);
    setTrace([]);
    setGraphEvents([]);
    setActiveRunId("");
    setGraphRunStatus("idle");
    setLastResponse(null);
    setQaSessionId("");
    setUserIdentity({
      ...DEFAULT_USER_IDENTITY,
      nickname: user?.display_name?.trim() || DEFAULT_USER_IDENTITY.nickname,
    });
    persistenceRevision.current = 0;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([checkBackendHealth(), listUsers()]).then((results) => {
      if (cancelled) return;
      const healthResult = results[0];
      const usersResult = results[1];
      if (healthResult.status === "fulfilled") {
        setConnection(healthResult.value.model_configured ? "live" : "needs-key");
      } else {
        setConnection("idle");
      }
      const registered = usersResult.status === "fulfilled" ? usersResult.value : [];
      setUsers(registered);
      if (usersResult.status === "rejected") {
        setToast({ text: "用户列表加载失败，已保留本地兼容用户", error: true });
      }
      let remembered = "";
      try {
        remembered = window.localStorage.getItem(ACTIVE_USER_PREFERENCE_KEY) || "";
      } catch {
        // Browser preferences are optional.
      }
      const selected = registered.some((user) => user.user_id === remembered)
        ? remembered
        : registered[0]?.user_id || "user_001";
      resetWorkspace(registered.find((user) => user.user_id === selected));
      setActiveUserId(selected);
    });
    return () => {
      cancelled = true;
    };
  }, [resetWorkspace]);

  useEffect(() => {
    if (!activeUserId) return;
    let cancelled = false;
    const cached = readLocalWorkspaceCache(activeUserId);
    try {
      window.localStorage.setItem(ACTIVE_USER_PREFERENCE_KEY, activeUserId);
    } catch {
      // Browser preferences are optional.
    }
    loadBackendWorkspaceState(activeUserId)
      .then((backendState) => {
        if (cancelled) return;
        const merged = mergeBackendProfile(
          backendState,
          cached?.profile || DEFAULT_PROFILE,
          cached?.scores || DEFAULT_SCORES,
        );
        setProfile(merged.profile);
        setBackendKnowledgeGaps(backendState.knowledge_gaps ?? []);
        setBackendCourseProgress(backendState.learning_progress ?? []);
        persistenceRevision.current = Math.max(
          persistenceRevision.current,
          Number(backendState.client_revision || 0),
        );
        const remoteState = backendState.frontend_state;
        if (remoteState && Object.keys(remoteState).length) {
          applyFrontendState(remoteState);
          if (
            !asRecord(remoteState.capability_assessment) &&
            cached?.frontendState &&
            asRecord(cached.frontendState.capability_assessment)
          ) {
            setCapabilityEvidence(
              normalizeCapabilityEvidence(
                asRecord(cached.frontendState.capability_assessment)?.evidence,
              ),
            );
          }
          if (
            !Array.isArray(remoteState.quiz_sessions) &&
            cached?.frontendState &&
            Array.isArray(cached.frontendState.quiz_sessions)
          ) {
            const cachedSessions = normalizeQuizSessions(
              cached.frontendState.quiz_sessions,
            );
            const requestedSessionId =
              typeof cached.frontendState.active_quiz_session_id === "string"
                ? cached.frontendState.active_quiz_session_id
                : "";
            setQuizSessions(cachedSessions);
            setActiveQuizSessionId(
              cachedSessions.some(
                (session) => session.id === requestedSessionId,
              )
                ? requestedSessionId
                : cachedSessions[0]?.id || "",
            );
          }
          if (
            !Array.isArray(remoteState.lecture_sessions) &&
            cached?.frontendState &&
            Array.isArray(cached.frontendState.lecture_sessions)
          ) {
            const cachedLectures = normalizeLectureSessions(
              cached.frontendState.lecture_sessions,
            );
            const requestedLectureId =
              typeof cached.frontendState.active_lecture_session_id === "string"
                ? cached.frontendState.active_lecture_session_id
                : "";
            setLectureSessions(cachedLectures);
            setActiveLectureSessionId(
              cachedLectures.some((lecture) => lecture.id === requestedLectureId)
                ? requestedLectureId
                : cachedLectures[0]?.id || "",
            );
          }
        } else if (cached?.frontendState) {
          applyFrontendState(cached.frontendState);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setConnection("idle");
        if (cached?.profile) setProfile(cached.profile);
        if (cached?.frontendState) applyFrontendState(cached.frontendState);
      })
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, [activeUserId, applyFrontendState]);

  useEffect(() => {
    if (!activeUserId) return;
    let cancelled = false;
    loadCapabilityScores(activeUserId)
      .then((result) => {
        if (!cancelled) setBackendCapabilityScores(result);
      })
      .catch(() => {
        // Compatibility fallback: local evidence remains available when an
        // older backend does not expose the v2 learner_metrics endpoints.
      });
    return () => {
      cancelled = true;
    };
  }, [activeUserId]);

  useEffect(() => {
    if (!hydrated || !activeUserId) return;
    const quizEvidence = capabilityEvidence.filter(
      (item) => item.sourceType === "quiz",
    );
    if (!quizEvidence.length) return;
    const syncKey = capabilityEvidenceSyncKey(activeUserId, quizEvidence);
    if (profileEvidenceSyncKey.current === syncKey) return;
    profileEvidenceSyncKey.current = syncKey;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void syncQuizProfileEvidence(
        activeUserId,
        ACTIVE_COURSE_ID,
        quizEvidence,
      )
        .then(async () => {
          const [capability, gaps] = await Promise.all([
            loadCapabilityScores(activeUserId),
            loadBackendKnowledgeGaps(activeUserId),
          ]);
          if (!cancelled) {
            setBackendCapabilityScores(capability);
            setBackendKnowledgeGapState(gaps);
          }
        })
        .catch(() => {
          // Keep the local evidence and retry after the next evidence change.
          if (!cancelled) profileEvidenceSyncKey.current = "";
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeUserId, capabilityEvidence, hydrated]);

  useEffect(() => {
    if (!activeUserId) return;
    let cancelled = false;
    loadBackendKnowledgeGaps(activeUserId)
      .then((result) => {
        if (!cancelled) setBackendKnowledgeGapState(result);
      })
      .catch(() => {
        // Compatibility fallback: older backends still expose knowledge_gaps
        // through the aggregate workspace state loaded above.
      });
    return () => {
      cancelled = true;
    };
  }, [activeUserId]);

  useEffect(() => {
    if (!activeUserId) return;
    let cancelled = false;
    const loadingTimer = window.setTimeout(() => {
      if (cancelled) return;
      setLearningPathLoading(true);
      setLearningPathError("");
    }, 0);
    loadUserLearningPath(activeUserId, ACTIVE_COURSE_ID)
      .then((result) => {
        if (!cancelled) setUserLearningPath(result);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setUserLearningPath(null);
        setLearningPathError(
          error instanceof Error ? error.message : "无法读取后端学习路径",
        );
      })
      .finally(() => {
        if (!cancelled) setLearningPathLoading(false);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(loadingTimer);
    };
  }, [activeUserId]);

  useEffect(() => {
    if (!hydrated || !activeUserId) return;
    const frontendState: FrontendStateSnapshot = {
      state_version: 1,
      qa_context_version: QA_CONTEXT_VERSION,
      messages: messages.slice(-500),
      history: history.slice(0, 100),
      memory_events: memoryEvents.slice(0, 500),
      pending_suggestions: pendingSuggestions.slice(0, 100),
      user_identity: userIdentity,
      qa_session_id: qaSessionId,
      capability_assessment: {
        model_version: ASSESSMENT_MODEL_VERSION,
        evidence: capabilityEvidence.slice(0, 2_000),
      },
      quiz_sessions: quizSessions.slice(0, 50),
      active_quiz_session_id: activeQuizSessionId,
      learning_progress: learningProgress,
      lecture_sessions: lectureSessions.slice(0, 50),
      active_lecture_session_id: activeLectureSessionId,
    };

    try {
      window.localStorage.setItem(
        workspaceCacheKey(activeUserId),
        JSON.stringify({ profile, scores, frontendState }),
      );
    } catch {
      // localStorage is only a recovery cache; SQLite remains authoritative.
    }

    const clientRevision = Math.max(
      Date.now(),
      persistenceRevision.current + 1,
    );
    persistenceRevision.current = clientRevision;
    const timer = window.setTimeout(() => {
      void saveBackendWorkspaceState(activeUserId, {
        profile,
        scores,
        frontend_state: frontendState,
        client_revision: clientRevision,
      }).catch(() => {
        // Keep the cache and retry on the next state change or application start.
      });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [
    history,
    activeUserId,
    hydrated,
    capabilityEvidence,
    memoryEvents,
    messages,
    pendingSuggestions,
    profile,
    qaSessionId,
    quizSessions,
    activeQuizSessionId,
    learningProgress,
    lectureSessions,
    activeLectureSessionId,
    scores,
    userIdentity,
  ]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function addSuggestions(response: AgentResponse) {
    const patches = response.profile_update_suggestions?.md_patches || [];
    // 能力分数不接受主观建议；这里只自动应用学习者画像字段。
    // Ability scores remain derived only from graded question/practice evidence.
    if (!patches.length) return;
    setProfile((current) => {
      const next = { ...current };
      for (const patch of patches) {
        const field = patch.path.replace(/^\/+/, "").split("/").pop() || patch.path;
        if (field === "level") {
          const value = String(patch.value ?? "");
          if (!["beginner", "intermediate", "advanced"].includes(value)) continue;
        }
        next[field] = patch.op === "remove" ? "" : String(patch.value ?? "");
      }
      return next;
    });
    setPendingSuggestions([]);
    setMemoryEvents((current) => [
      {
        id: uid("profile-auto-update"),
        title: "知链已更新学习者画像",
        detail: `根据本次学习行为自动更新 ${patches.length} 项画像信息。`,
        time: new Date().toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
      ...current,
    ]);
  }

  async function runAgent(request: AgentRequest): Promise<AgentResponse> {
    setBusy(true);
    setTrace(PENDING_TRACE);
    setGraphEvents([]);
    setActiveRunId("");
    setGraphRunStatus("created");
    setConnection("checking");
    try {
      const response = await dispatchToCentralOrchestrator(
        {
          ...request,
          learning_progress: learningProgress.agentContext,
        },
        {
          onTrace: setTrace,
          onRunCreated: setActiveRunId,
          onStatus: setGraphRunStatus,
          onEvent: (event) => {
            setGraphEvents((current) => {
              if (
                event.event_id &&
                current.some((item) => item.event_id === event.event_id)
              ) {
                return current;
              }
              return [...current, event];
            });
          },
        },
      );
      setConnection("live");
      setGraphRunStatus("completed");
      setTrace(response.agent_trace || []);
      setLastResponse(response);
      addSuggestions(response);
      return response;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "无法连接中央调度器";
      setConnection(message.includes("DEEPSEEK_API_KEY") ? "needs-key" : "idle");
      setGraphRunStatus((current) =>
        current === "cancelled" ? current : "failed",
      );
      setTrace([]);
      setLastResponse(null);
      setToast({
        text: `${message}。本次请求未生成任何本地演示内容`,
        error: true,
      });
      throw error instanceof Error ? error : new Error(message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshMemory(showToast = true) {
    if (!activeUserId) return;
    setMemoryBusy(true);
    try {
      const [backendState, capabilityState, knowledgeGapState] = await Promise.all([
        loadBackendWorkspaceState(activeUserId),
        loadCapabilityScores(activeUserId),
        loadBackendKnowledgeGaps(activeUserId).catch(() => null),
      ]);
      const merged = mergeBackendProfile(backendState, profile, scores);
      setProfile(merged.profile);
      setBackendKnowledgeGaps(backendState.knowledge_gaps ?? []);
      setBackendCourseProgress(backendState.learning_progress ?? []);
      setBackendCapabilityScores(capabilityState);
      if (knowledgeGapState) setBackendKnowledgeGapState(knowledgeGapState);
      persistenceRevision.current = Math.max(
        persistenceRevision.current,
        Number(backendState.client_revision || 0),
      );
      if (
        showToast &&
        backendState.frontend_state &&
        Object.keys(backendState.frontend_state).length
      ) {
        applyFrontendState(backendState.frontend_state);
      }
      if (showToast) setToast({ text: "已从后端刷新 Memory" });
    } catch (error) {
      setToast({
        text: error instanceof Error ? error.message : "Memory 刷新失败",
        error: true,
      });
    } finally {
      setMemoryBusy(false);
    }
  }

  async function saveMemory(profileOverride?: LearnerProfile) {
    if (!activeUserId) return;
    setMemoryBusy(true);
    try {
      const profileToSave = profileOverride ?? profile;
      const backendProfile = await saveBackendProfile(
        activeUserId,
        profileToSave,
        scores,
      );
      const merged = mergeBackendProfile(backendProfile, profileToSave, scores);
      setProfile(merged.profile);
      setMemoryEvents((events) => [
        {
          id: uid("memory-sync"),
          title: "Memory 已同步到后端",
          detail: "结构化画像和能力分数已写入用户画像存储。",
          time: new Date().toLocaleString("zh-CN", {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          }),
        },
        ...events,
      ]);
      setToast({ text: "Memory 已保存到后端" });
    } catch (error) {
      setToast({
        text: error instanceof Error ? error.message : "Memory 保存失败",
        error: true,
      });
    } finally {
      setMemoryBusy(false);
    }
  }

  async function switchActiveUser(nextUser: UserSummary) {
    if (!nextUser.user_id || nextUser.user_id === activeUserId) {
      setUserDialog(null);
      return;
    }
    const frontendState: FrontendStateSnapshot = {
      state_version: 1,
      qa_context_version: QA_CONTEXT_VERSION,
      messages: messages.slice(-500),
      history: history.slice(0, 100),
      memory_events: memoryEvents.slice(0, 500),
      pending_suggestions: pendingSuggestions.slice(0, 100),
      user_identity: userIdentity,
      qa_session_id: qaSessionId,
      capability_assessment: {
        model_version: ASSESSMENT_MODEL_VERSION,
        evidence: capabilityEvidence.slice(0, 2_000),
      },
      quiz_sessions: quizSessions.slice(0, 50),
      active_quiz_session_id: activeQuizSessionId,
      learning_progress: learningProgress,
      lecture_sessions: lectureSessions.slice(0, 50),
      active_lecture_session_id: activeLectureSessionId,
    };
    setMemoryBusy(true);
    try {
      if (activeUserId) {
        const revision = Math.max(Date.now(), persistenceRevision.current + 1);
        await saveBackendWorkspaceState(activeUserId, {
          profile,
          scores,
          frontend_state: frontendState,
          client_revision: revision,
        });
      }
      // Preflight the target workspace. A failed switch must leave the current UI intact.
      await loadBackendWorkspaceState(nextUser.user_id);
      setHydrated(false);
      resetWorkspace(nextUser);
      setActiveUserId(nextUser.user_id);
      setUserDialog(null);
      setToast({ text: `已切换到“${nextUser.display_name || nextUser.user_id}”` });
    } catch (error) {
      setToast({
        text: error instanceof Error ? `切换失败：${error.message}` : "用户切换失败",
        error: true,
      });
    } finally {
      setMemoryBusy(false);
    }
  }

  const pageMeta = {
    chat: {
      title: "聊天问答",
      detail: "基于当前用户画像与领域知识生成个性化回答",
    },
    quiz: {
      title: "Quiz 生成",
      detail: "让中央调度器生成、审查并返回结构化测验",
    },
    lecture: {
      title: "学习讲义",
      detail: "根据当前画像、学习进度与知识库生成个性化阶段讲义",
    },
    memory: {
      title: "用户中心",
      detail: "查看学习画像、知识漏洞、资源匹配与个性化设置",
    },
    progress: {
      title: "学习进度",
      detail: "依据学习证据评估从行业入门到岗位胜任的成长阶段",
    },
  }[activeView];

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      {!sidebarCollapsed && (
        <Sidebar
          activeView={activeView}
          setActiveView={setActiveView}
          connection={connection}
          userIdentity={userIdentity}
          setUserIdentity={setUserIdentity}
          busy={busy}
          trace={trace}
          graphEvents={graphEvents}
          runId={activeRunId}
          runStatus={graphRunStatus}
          response={lastResponse}
          activeUserId={activeUserId}
          onSwitchUser={() => setUserDialog("switch")}
          onCreateUser={() => setUserDialog("create")}
          onCollapse={() => setSidebarCollapsed(true)}
        />
      )}
      <main className="workspace">
        <header className="topbar">
          <div className="topbar-start">
            {sidebarCollapsed && (
              <SidebarToggleButton
                collapsed
                onToggle={() => setSidebarCollapsed(false)}
              />
            )}
            <div className="page-heading">
              <h1>{pageMeta.title}</h1>
              <p>{pageMeta.detail}</p>
            </div>
          </div>
          <div className="topbar-actions">
            <span className="orchestrator-badge">中央调度器 · HTTP v2</span>
            <button
              type="button"
              className="more-info-button"
              aria-controls="more-info-drawer"
              aria-expanded={moreInfoOpen}
              onClick={() => setMoreInfoOpen(true)}
            >
              更多信息
              <span aria-hidden="true">···</span>
            </button>
          </div>
        </header>
        <div className="page-content">
          {activeView === "chat" && (
            <ChatView
              userId={activeUserId}
              messages={messages}
              setMessages={setMessages}
              history={history}
              setHistory={setHistory}
              busy={busy}
              profile={profile}
              scores={scores}
              memoryEvents={memoryEvents}
              runAgent={runAgent}
              userIdentity={userIdentity}
              qaSessionId={qaSessionId}
              setQaSessionId={setQaSessionId}
              recommendations={learningRecommendations}
            />
          )}
          {activeView === "quiz" && (
            <QuizView
              userId={activeUserId}
              busy={busy}
              profile={profile}
              scores={scores}
              recommendations={learningRecommendations}
              runAgent={runAgent}
              sessions={quizSessions}
              activeLecture={
                lectureSessions.find(
                  (lecture) =>
                    lecture.id === activeLectureSessionId &&
                    (!userLearningPath ||
                      userLearningPath.chapters.some(
                        (chapter) => chapter.chapter_id === lecture.chapterId,
                      )),
                ) ?? null
              }
              currentChapterId={
                userLearningPath?.current_chapter_id || ACTIVE_CHAPTER_ID
              }
              activeSessionId={activeQuizSessionId}
              onActiveSessionChange={setActiveQuizSessionId}
              onSessionChange={(session) =>
                setQuizSessions((current) =>
                  upsertQuizSession(current, session),
                )
              }
              onQuestionSubmitted={(session, questionId) => {
                const evidence = assessmentEvidenceForSession(
                  session,
                  questionId,
                );
                setCapabilityEvidence((current) =>
                  mergeCapabilityEvidence(current, evidence),
                );
              }}
              onFinished={async (session) => {
                const evidence = assessmentEvidenceForSession(session);
                const nextEvidence = mergeCapabilityEvidence(
                  capabilityEvidence,
                  evidence,
                );
                const nextAssessment = calculateCapabilityAssessment(nextEvidence);
                setCapabilityEvidence(nextEvidence);
                const progress = quizSessionProgress(session);
                const changedDimensions = [
                  ...new Set(
                    evidence.map(
                      (item) =>
                        nextAssessment.dimensions[item.dimension].shortLabel,
                    ),
                  ),
                ];
                const detail = `完成“${session.topic}”测验：${progress.earnedPoints}/${progress.possiblePoints} 分（${Math.round((progress.accuracy || 0) * 100)}%），${progress.correct}/${progress.total} 道达到正确标准；已保存题目、作答、逐题评分和知识来源，并更新${changedDimensions.join("、")}。`;
                setMemoryEvents((events) => [
                  {
                    id: uid("quiz-memory"),
                    title: "Quiz 学习记录",
                    detail,
                    time: new Date().toLocaleString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                  },
                  ...events,
                ]);
                try {
                  profileEvidenceSyncKey.current = capabilityEvidenceSyncKey(
                    activeUserId,
                    nextEvidence,
                  );
                  await submitPersistedQuizAttempts(activeUserId, session);
                  await syncQuizProfileEvidence(
                    activeUserId,
                    ACTIVE_COURSE_ID,
                    nextEvidence,
                  );
                  await refreshMemory(false);
                  setToast({ text: "Quiz 作答、能力证据和知识漏洞已写入后端" });
                } catch (error) {
                  setToast({
                    text: error instanceof Error ? error.message : "Quiz 结果写入失败",
                    error: true,
                  });
                }
              }}
            />
          )}
          {activeView === "lecture" && (
            <LectureView
              userId={activeUserId}
              sessions={lectureSessions}
              activeSessionId={activeLectureSessionId}
              onActiveSessionChange={setActiveLectureSessionId}
              onSessionCreated={(session) => {
                setLectureSessions((current) => upsertLectureSession(current, session));
                setActiveLectureSessionId(session.id);
                setMemoryEvents((events) => [
                  {
                    id: uid("lecture-memory"),
                    title: "学习讲义已生成",
                    detail: `已保存“${session.title}”，章节 ${session.chapterId}，包含 ${session.sections.length} 个部分和 ${session.sourceRefs.length} 个知识来源。`,
                    time: new Date().toLocaleString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                  },
                  ...events,
                ]);
              }}
              profile={profile}
              scores={scores}
              progress={learningProgress}
              learningPath={userLearningPath}
              capabilityEvidence={effectiveCapabilityEvidence}
              busy={busy}
              runAgent={runAgent}
              onProgressChanged={() => refreshMemory(false)}
            />
          )}
          {activeView === "memory" && (
            <UserCenterView
              userId={activeUserId}
              profile={profile}
              assessment={capabilityAssessment}
              capabilityOverall={
                activeBackendCapabilityScores?.profileScore.overall ??
                learningProgress.provisionalMastery
              }
              progress={learningProgress}
              setProfile={setProfile}
              knowledgeGaps={effectiveKnowledgeGaps}
              knowledgeGapSummary={activeKnowledgeGapState?.summary ?? null}
              events={memoryEvents}
              busy={memoryBusy}
              onReload={() => refreshMemory()}
              onSaved={saveMemory}
            />
          )}
          {activeView === "progress" && (
            <LearningProgressView
              progress={learningProgress}
              learningPath={userLearningPath}
              learningPathLoading={learningPathLoading}
              learningPathError={learningPathError}
              onNavigate={setActiveView}
            />
          )}
        </div>
      </main>
      <MoreInfoDrawer
        userId={activeUserId}
        open={moreInfoOpen}
        onClose={() => setMoreInfoOpen(false)}
        progress={learningProgress}
        profile={profile}
        scores={scores}
        busy={busy}
        runAgent={runAgent}
      />
      <UserAccessDialog
        key={userDialog || "user-dialog-closed"}
        mode={userDialog}
        users={users}
        activeUserId={activeUserId}
        onClose={() => setUserDialog(null)}
        onModeChange={setUserDialog}
        onSelect={(user) => void switchActiveUser(user)}
        onCreated={(user) => {
          setUsers((current) => [
            user,
            ...current.filter((item) => item.user_id !== user.user_id),
          ]);
          setHydrated(false);
          resetWorkspace(user);
          setActiveUserId(user.user_id);
          setUserDialog(null);
          setToast({ text: `已创建学习者“${user.display_name || user.user_id}”` });
        }}
      />
      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.text}</div>}
    </div>
  );
}

function Sidebar({
  activeView,
  setActiveView,
  connection,
  userIdentity,
  setUserIdentity,
  busy,
  trace,
  graphEvents,
  runId,
  runStatus,
  response,
  activeUserId,
  onSwitchUser,
  onCreateUser,
  onCollapse,
}: {
  activeView: View;
  setActiveView: (view: View) => void;
  connection: ConnectionState;
  userIdentity: UserIdentity;
  setUserIdentity: React.Dispatch<React.SetStateAction<UserIdentity>>;
  busy: boolean;
  trace: AgentTrace[];
  graphEvents: GraphRunEvent[];
  runId: string;
  runStatus: GraphRunStatus;
  response: AgentResponse | null;
  activeUserId: string;
  onSwitchUser: () => void;
  onCreateUser: () => void;
  onCollapse: () => void;
}) {
  const items: Array<{ id: View; symbol: string; label: string }> = [
    { id: "progress", symbol: "进", label: "学习进度" },
    { id: "chat", symbol: "问", label: "聊天问答" },
    { id: "quiz", symbol: "测", label: "Quiz 生成" },
    { id: "lecture", symbol: "学", label: "学习讲义" },
    { id: "memory", symbol: "人", label: "用户中心" },
  ];

  return (
    <aside className="sidebar" id="zlink-sidebar">
      <div className="brand">
        <SidebarToggleButton
          collapsed={false}
          className="sidebar-toggle-in-sidebar"
          onToggle={onCollapse}
        />
        <span className="brand-logo-shell" aria-hidden="true">
          <img
            className="brand-logo"
            src="/zhilian-logo.png"
            alt=""
            width={44}
            height={44}
          />
        </span>
        <span className="brand-copy">
          <strong>知链</strong>
          <small>ZLink</small>
        </span>
      </div>
      <nav className="nav-list" aria-label="主导航">
        {items.map((item) => (
          <button
            type="button"
            key={item.id}
            className={`nav-button ${activeView === item.id ? "active" : ""}`}
            aria-current={activeView === item.id ? "page" : undefined}
            aria-label={item.id === "memory" ? "Memory 用户中心" : item.label}
            onClick={() => setActiveView(item.id)}
          >
            <span className="nav-symbol">{item.symbol}</span>
            <span className="nav-text">{item.label}</span>
          </button>
        ))}
      </nav>
      <AgentActivity
        busy={busy}
        trace={trace}
        graphEvents={graphEvents}
        runId={runId}
        runStatus={runStatus}
        response={response}
        compact
      />
      <footer className="sidebar-footer">
        <div className="connection-card">
          <span className={`status-dot ${connection}`} />
          <span>{connectionText(connection)}</span>
        </div>
        <UserProfileControl
          identity={userIdentity}
          onChange={setUserIdentity}
          userId={activeUserId}
          onSwitchUser={onSwitchUser}
          onCreateUser={onCreateUser}
        />
      </footer>
    </aside>
  );
}

function ChatView({
  userId,
  messages,
  setMessages,
  history,
  setHistory,
  busy,
  profile,
  scores,
  memoryEvents,
  runAgent,
  userIdentity,
  qaSessionId,
  setQaSessionId,
  recommendations,
}: {
  userId: string;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  history: string[];
  setHistory: React.Dispatch<React.SetStateAction<string[]>>;
  busy: boolean;
  profile: LearnerProfile;
  scores: ScoreMap;
  memoryEvents: MemoryEvent[];
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  userIdentity: UserIdentity;
  qaSessionId: string;
  setQaSessionId: React.Dispatch<React.SetStateAction<string>>;
  recommendations: LearningRecommendations;
}) {
  const [input, setInput] = useState("");
  const [historyPanelCollapsed, setHistoryPanelCollapsed] = useState(false);
  const [historyPanelPeek, setHistoryPanelPeek] = useState(false);
  const [historyPreferenceReady, setHistoryPreferenceReady] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      // Restore the persisted panel state after the browser storage is available.
      setHistoryPanelCollapsed(
        window.localStorage.getItem(CHAT_HISTORY_PANEL_PREFERENCE_KEY) === "true",
      );
    } catch {
      // Keep the question history visible when local preferences are unavailable.
    } finally {
      setHistoryPreferenceReady(true);
    }
  }, []);

  useEffect(() => {
    if (!historyPreferenceReady) return;
    try {
      window.localStorage.setItem(
        CHAT_HISTORY_PANEL_PREFERENCE_KEY,
        String(historyPanelCollapsed),
      );
    } catch {
      // This preference is optional and must not block chat.
    }
  }, [historyPanelCollapsed, historyPreferenceReady]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [busy, messages]);

  async function sendQuestion(prompt: string) {
    const clean = prompt.trim();
    if (!clean || busy) return;
    setInput("");
    setMessages((items) => [
      ...items,
      { id: uid("user"), role: "user", content: clean },
    ]);
    setHistory((items) => [clean, ...items.filter((item) => item !== clean)]);

    const request = buildAgentRequest({
      userId,
      courseId: ACTIVE_COURSE_ID,
      chapterId: ACTIVE_CHAPTER_ID,
      prompt: clean,
      contentType: "qa",
      scores,
      profile: {
        ...profile,
        knowledge_domain: "数控车铣加工、多轴数控加工与数控机床安全操作",
        active_learning_topic: recommendations.primaryTopic,
        recent_memory: memoryEvents
          .slice(0, 6)
          .map((event) => `${event.title}：${event.detail}`),
      },
      qaSessionId: qaSessionId || undefined,
    });
    try {
      const result = await runAgent(request);
      if (result.qa_session_id) setQaSessionId(result.qa_session_id);
      const payload = asQaPayload(result);
      const content =
        payload?.answer ||
        result.final_output?.summary ||
        "中央调度器已完成任务，但没有返回可展示的问答内容。";
      setMessages((items) => [
        ...items,
        {
          id: uid("assistant"),
          role: "assistant",
          content,
          followUps: payload?.follow_ups,
        },
      ]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        {
          id: uid("assistant-error"),
          role: "assistant",
          content:
            error instanceof Error
              ? `本次请求失败：${error.message}`
              : "本次请求失败，请检查后端服务。",
        },
      ]);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void sendQuestion(input);
  }

  const showWelcome = messages.length === 1;

  const showHistory = history.length > 0 || !showWelcome;
  const historyPanelVisible =
    showHistory && (!historyPanelCollapsed || historyPanelPeek);

  return (
    <div
      className={`chat-layout ${showWelcome && !showHistory ? "welcome-layout" : ""} ${historyPanelCollapsed ? "history-panel-collapsed" : ""}`}
    >
      <section className={`chat-panel ${showWelcome ? "welcome-state" : ""}`}>
        <div className="message-scroll" ref={scrollRef}>
          <div className="messages">
            {showWelcome && (
              <div className="welcome">
                <h2>今天想从哪个知识点开始？</h2>
                <div className="welcome-intro">
                  <span className="welcome-logo-shell" aria-hidden="true">
                    <img
                      src="/zhilian-logo.png"
                      alt=""
                      width={30}
                      height={30}
                    />
                  </span>
                  <p>{INITIAL_MESSAGE.content}</p>
                </div>
                <p className="recommendation-context" aria-live="polite">
                  {recommendations.contextLabel}
                </p>
                <div className="prompt-grid">
                  {recommendations.chatPrompts.map((prompt) => (
                    <button
                      type="button"
                      className="prompt-card"
                      key={prompt}
                      onClick={() => void sendQuestion(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!showWelcome && messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <div className="message-avatar">
                  {message.role === "assistant" ? (
                    <img
                      className="message-logo"
                      src="/zhilian-logo.png"
                      alt=""
                      width={26}
                      height={26}
                      aria-hidden="true"
                    />
                  ) : (
                    <UserAvatar
                      avatarId={userIdentity.avatarId}
                      className="message-user-avatar"
                    />
                  )}
                </div>
                <div className="message-body">
                  <p className="message-author">
                    {message.role === "assistant" ? "知链助手" : userIdentity.nickname}
                  </p>
                  {message.role === "assistant" ? (
                    <MarkdownContent content={message.content} />
                  ) : (
                    <div className="message-text">{message.content}</div>
                  )}
                  {!!message.followUps?.length && (
                    <div className="followups">
                      {message.followUps.map((followUp) => (
                        <button
                          type="button"
                          className="followup-button"
                          key={followUp}
                          onClick={() => void sendQuestion(followUp)}
                        >
                          {followUp}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            ))}
            {busy && (
              <article className="message assistant">
                <div className="message-avatar">
                  <img
                    className="message-logo"
                    src="/zhilian-logo.png"
                    alt=""
                    width={26}
                    height={26}
                    aria-hidden="true"
                  />
                </div>
                <div className="message-body">
                  <p className="message-author">中央调度器处理中</p>
                  <div className="typing" aria-label="正在生成">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </article>
            )}
          </div>
        </div>
        <div className="composer-wrap">
          <form className="composer" onSubmit={onSubmit}>
            <textarea
              value={input}
              aria-label="输入学习问题"
              data-testid="chat-input"
              placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendQuestion(input);
                }
              }}
            />
            <div className="composer-actions">
              <div className="composer-meta">
                <span className="mini-chip">QA</span>
                <span>{profile.preference}</span>
              </div>
              <button
                type="submit"
                className="send-button"
                aria-label="发送问题"
                data-testid="chat-send"
                disabled={busy || !input.trim()}
              >
                ↑
              </button>
            </div>
          </form>
        </div>
      </section>
      {historyPanelVisible && (
        <RecentHistoryPanel
          history={history}
          overlay={historyPanelCollapsed}
          onClose={() => {
            setHistoryPanelCollapsed(true);
            setHistoryPanelPeek(false);
          }}
          onLeave={() => {
            if (historyPanelCollapsed) setHistoryPanelPeek(false);
          }}
          onSelect={(question) => {
            setInput(question);
            setHistoryPanelPeek(false);
          }}
        />
      )}
      {showHistory && historyPanelCollapsed && !historyPanelPeek && (
        <button
          type="button"
          className="history-edge-trigger"
          aria-label="显示最近问答"
          title="显示最近问答"
          onMouseEnter={() => setHistoryPanelPeek(true)}
          onFocus={() => setHistoryPanelPeek(true)}
          onClick={() => setHistoryPanelCollapsed(false)}
        >
          <span aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

function RecentHistoryPanel({
  history,
  overlay,
  onClose,
  onLeave,
  onSelect,
}: {
  history: string[];
  overlay: boolean;
  onClose: () => void;
  onLeave: () => void;
  onSelect: (question: string) => void;
}) {
  return (
    <aside
      className={`recent-history-panel ${overlay ? "overlay" : ""}`}
      id="recent-question-history"
      onMouseLeave={onLeave}
    >
      <div className="recent-history-header">
        <div>
          <h3>最近问答</h3>
          <p>{history.length ? `${history.length} 条本地记录` : "暂无问答记录"}</p>
        </div>
        <button
          type="button"
          className="panel-collapse-button"
          aria-label="隐藏最近问答"
          title="隐藏最近问答"
          onClick={onClose}
        >
          <span className="panel-collapse-icon" aria-hidden="true" />
        </button>
      </div>
      <div className="recent-history-list">
        {history.length ? (
          history.slice(0, 20).map((item, index) => (
            <button
              type="button"
              className="recent-history-item"
              key={`${item}-${index}`}
              title={item}
              onClick={() => onSelect(item)}
            >
              <span>{item}</span>
              <small>填入输入框</small>
            </button>
          ))
        ) : (
          <div className="recent-history-empty">
            发送问题后，记录会自动保存在这里。
          </div>
        )}
      </div>
    </aside>
  );
}

function graphEventAgentName(agentId?: string, displayName?: string): string {
  if (displayName) return displayName;
  if (!agentId) return "中央调度器";
  return AGENT_LABELS[agentId] || agentId.replaceAll("_", " ");
}

function graphPayloadValue(value: unknown): string {
  if (Array.isArray(value)) {
    if (!value.length) return "0 项";
    const first = value[0];
    return typeof first === "string"
      ? `${value.length} 项 · ${first}`
      : `${value.length} 项`;
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return keys.length ? `${keys.length} 个字段` : "已生成";
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  const text = String(value ?? "").trim();
  return text.length > 44 ? `${text.slice(0, 41)}...` : text;
}

function graphPayloadSummary(payloadRefs?: GraphPayloadRefs) {
  if (!payloadRefs) return [];
  const entries = Object.entries(payloadRefs).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  entries.sort(([left], [right]) => {
    const priority = Object.keys(PAYLOAD_REF_LABELS);
    const leftIndex = priority.indexOf(left);
    const rightIndex = priority.indexOf(right);
    return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex);
  });
  return entries.slice(0, 5).map(([key, value]) => ({
    key,
    label: PAYLOAD_REF_LABELS[key] || key.replaceAll("_", " "),
    value: graphPayloadValue(value),
  }));
}

function AgentActivity({
  busy,
  trace,
  graphEvents,
  runId,
  runStatus,
  response,
  compact = false,
}: {
  busy: boolean;
  trace: AgentTrace[];
  graphEvents: GraphRunEvent[];
  runId: string;
  runStatus: GraphRunStatus;
  response: AgentResponse | null;
  compact?: boolean;
}) {
  const activities = graphEvents.filter(
    (event): event is AgentActivityEvent => event.event_type === "agent.activity",
  );
  const handoffs = graphEvents.filter(
    (event): event is AgentMessageEvent => event.event_type === "agent.message",
  );
  const latestActivity = activities.at(-1);
  const agents = Array.from(
    new Map(
      activities.map((event) => [
        event.agent_id || event.agent_display_name || "agent",
        graphEventAgentName(event.agent_id, event.agent_display_name),
      ]),
    ).values(),
  );
  const displayed = graphEvents.length ? [] : busy ? PENDING_TRACE : trace;
  const ragEvidence = response?.rag_package?.evidence ?? [];
  const effectiveStatus = busy && runStatus === "created" ? "running" : runStatus;

  return (
    <section className={`activity-panel ${compact ? "sidebar-agent-activity" : ""}`}>
      <div className="activity-header">
        <div>
          <h3>多 Agent 协作</h3>
          <p>
            {graphEvents.length || runId
              ? RUN_STATUS_LABELS[effectiveStatus]
              : "等待任务"}
          </p>
        </div>
        <span className={`run-status-pill ${effectiveStatus}`}>
          {effectiveStatus === "running" && <span aria-hidden="true" />}
          {RUN_STATUS_LABELS[effectiveStatus]}
        </span>
      </div>

      {(runId || graphEvents.length > 0) && (
        <div className="agent-run-overview">
          <div className="agent-section-heading">
            <h4>当前运行状态</h4>
            <span title={runId}>{runId ? runId.replace(/^run_/, "#") : "创建中"}</span>
          </div>
          <div className="run-overview-grid">
            <div>
              <small>当前 Agent</small>
              <strong>
                {latestActivity
                  ? graphEventAgentName(
                      latestActivity.agent_id,
                      latestActivity.agent_display_name,
                    )
                  : effectiveStatus === "completed"
                    ? "中央调度器"
                    : "正在分配"}
              </strong>
            </div>
            <div>
              <small>当前节点</small>
              <strong title={latestActivity?.node_id || ""}>
                {latestActivity?.node_id
                  ? TRACE_LABELS[latestActivity.node_id] || latestActivity.node_id
                  : "—"}
              </strong>
            </div>
            <div>
              <small>参与 Agent</small>
              <strong>{agents.length}</strong>
            </div>
            <div>
              <small>实时事件</small>
              <strong>{graphEvents.length}</strong>
            </div>
          </div>
          {!!agents.length && (
            <div className="agent-participant-list" aria-label="参与协作的 Agent">
              {agents.map((agent) => (
                <span key={agent}>{agent}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {!!graphEvents.length && (
        <div className="agent-event-section handoff-section">
          <div className="agent-section-heading">
            <h4>Agent 协作流</h4>
            <span>{handoffs.length} 次交接</span>
          </div>
          {handoffs.length ? (
            <div className="handoff-list">
              {handoffs.map((event, index) => {
                const payload = graphPayloadSummary(event.payload_refs);
                return (
                  <article
                    className="handoff-item"
                    key={event.event_id || `${event.from_agent}-${event.to_agent}-${index}`}
                  >
                    <div className="handoff-route">
                      <span>{graphEventAgentName(event.from_agent)}</span>
                      <b aria-label="交接给">→</b>
                      <span>{graphEventAgentName(event.to_agent)}</span>
                    </div>
                    <div className="handoff-message">
                      <strong>{event.display_text || "交接任务"}</strong>
                      <small>{event.message_type || "handoff"}</small>
                    </div>
                    {!!event.detail && <p>{event.detail}</p>}
                    {!!payload.length && (
                      <div className="event-payload-list">
                        {payload.map((item) => (
                          <span key={`${event.event_id}-${item.key}`}>
                            <b>{item.label}</b>{item.value}
                          </span>
                        ))}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="agent-event-empty">任务仍在首个 Agent 内处理中，暂未发生交接。</p>
          )}
        </div>
      )}

      {!!activities.length && (
        <div className="agent-event-section activity-timeline-section">
          <div className="agent-section-heading">
            <h4>节点执行时间线</h4>
            <span>{activities.length} 个节点</span>
          </div>
          <div className="trace-list live-agent-trace">
            {activities.map((event, index) => {
              const isCurrent = busy && index === activities.length - 1;
              const payload = graphPayloadSummary(event.payload_refs);
              return (
                <div
                  className={`trace-item ${isCurrent ? "running" : "done"}`}
                  key={event.event_id || `${event.node_id}-${index}`}
                >
                  <span className="trace-node">
                    {isCurrent ? "•" : "✓"}
                  </span>
                  <div className="trace-copy">
                    <small className="trace-agent-name">
                      {graphEventAgentName(event.agent_id, event.agent_display_name)}
                    </small>
                    <strong title={event.node_id || ""}>
                      {(event.node_id && TRACE_LABELS[event.node_id]) ||
                        event.display_text ||
                        event.node_id ||
                        "Agent 节点"}
                    </strong>
                    <p>{event.detail || event.display_text || "已完成当前步骤"}</p>
                    {!!payload.length && (
                      <div className="event-payload-list">
                        {payload.map((item) => (
                          <span key={`${event.event_id}-${item.key}`}>
                            <b>{item.label}</b>{item.value}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {displayed.length ? (
        <div className="trace-list legacy-agent-trace">
          {displayed.map((item, index) => {
            const state =
              item.status === "running"
                ? "running"
                : item.status === "queued"
                  ? "queued"
                  : "done";
            return (
              <div className={`trace-item ${state}`} key={`${item.node}-${index}`}>
                <span className="trace-node">
                  {state === "done" ? "✓" : state === "running" ? "•" : index + 1}
                </span>
                <div className="trace-copy">
                  <strong>{TRACE_LABELS[item.node] || item.node}</strong>
                  <p>{item.summary}</p>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        !graphEvents.length && (
          <div className="empty-activity">
            发起问答、Quiz 或讲义任务后，这里会实时展示 Agent 节点、协作交接与传递摘要。
          </div>
        )
      )}
      {!!response && (
        <div className="report-card">
          <h4>质量报告</h4>
          <div className="metric-row">
            <span>任务状态</span>
            <strong>{response.status}</strong>
          </div>
          <div className="metric-row">
            <span>证据覆盖率</span>
            <strong>
              {Math.round((response.check_report?.evidence_coverage || 0) * 100)}%
            </strong>
          </div>
          <div className="metric-row">
            <span>RAG 置信度</span>
            <strong>
              {Math.round((response.rag_package?.confidence || 0) * 100)}%
            </strong>
          </div>
          <div className="metric-row">
            <span>安全审查</span>
            <strong>{response.safety_report?.status || "—"}</strong>
          </div>
        </div>
      )}
      {!!ragEvidence.length && (
        <div className="rag-source-card">
          <div className="rag-source-heading">
            <h4>知识库依据</h4>
            <span>{response?.rag_package?.knowledge_base_version || "当前版本"}</span>
          </div>
          <div className="rag-source-list">
            {ragEvidence.slice(0, 4).map((item, index) => {
              const source = item.source_file ?? item.source_doc ?? "未知来源";
              return (
                <div className="rag-source-item" key={`${item.chunk_id || source}-${index}`}>
                  <strong title={source}>{source.split(/[\\/]/).pop()}</strong>
                  <span>
                    {item.page_label ? `第 ${item.page_label} 页 · ` : ""}
                    匹配度 {Math.round(Number(item.score || 0) * 100)}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function QuizView({
  userId,
  busy,
  profile,
  scores,
  recommendations,
  runAgent,
  sessions,
  activeLecture,
  currentChapterId,
  activeSessionId,
  onActiveSessionChange,
  onSessionChange,
  onQuestionSubmitted,
  onFinished,
}: {
  userId: string;
  busy: boolean;
  profile: LearnerProfile;
  scores: ScoreMap;
  recommendations: LearningRecommendations;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  sessions: QuizSession[];
  activeLecture: LectureSession | null;
  currentChapterId: string;
  activeSessionId: string;
  onActiveSessionChange: (sessionId: string) => void;
  onSessionChange: (session: QuizSession) => void;
  onQuestionSubmitted: (session: QuizSession, questionId: string) => void;
  onFinished: (session: QuizSession) => void | Promise<void>;
}) {
  const primaryQuiz = recommendations.quizOptions[0];
  const [topicOverride, setTopicOverride] = useState<string | null>(null);
  const [count, setCount] = useState(String(DEFAULT_QUIZ_QUESTION_COUNT));
  const [generationProgress, setGenerationProgress] = useState("");
  const generationLock = useRef(false);
  const [gradingQuestionId, setGradingQuestionId] = useState("");
  const recommendedDifficulty =
    profile.level === "advanced"
      ? "hard"
      : profile.level === "intermediate"
        ? "medium"
        : "easy";
  const [difficultyOverride, setDifficultyOverride] = useState<string | null>(
    null,
  );
  const [focusOverride, setFocusOverride] = useState<string | null>(null);
  const [linkToCurrentLecture, setLinkToCurrentLecture] = useState(true);
  const [configPanelCollapsed, setConfigPanelCollapsed] = useState(false);
  const [configPanelPeek, setConfigPanelPeek] = useState(false);
  const [configPreferenceReady, setConfigPreferenceReady] = useState(false);
  const topic = topicOverride ?? primaryQuiz.topic;
  const difficulty = difficultyOverride ?? recommendedDifficulty;
  const focus = focusOverride ?? primaryQuiz.focus;
  const [quizError, setQuizError] = useState<string | null>(null);
  const [panel, setPanel] = useState<"current" | "history">(
    activeSessionId ? "current" : "history",
  );
  const activeSession =
    sessions.find((session) => session.id === activeSessionId) ?? null;
  const displayedQuizError = quizError || activeSession?.generationError || null;
  const generationRunning =
    !!generationProgress || activeSession?.generationStatus === "generating";
  const blueprint = useMemo(
    () => createQuizBlueprint(count, scores),
    [count, scores],
  );
  const blueprintSummary = useMemo(
    () => summarizeQuizBlueprint(blueprint),
    [blueprint],
  );
  const configPanelVisible = !configPanelCollapsed || configPanelPeek;

  useEffect(() => {
    try {
      // Restoring a device-local layout preference requires one client-only update.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConfigPanelCollapsed(
        window.localStorage.getItem(QUIZ_CONFIG_PANEL_PREFERENCE_KEY) === "true",
      );
    } catch {
      // Keep the generation settings visible when local preferences are unavailable.
    } finally {
      setConfigPreferenceReady(true);
    }
  }, []);

  useEffect(() => {
    if (!configPreferenceReady) return;
    try {
      window.localStorage.setItem(
        QUIZ_CONFIG_PANEL_PREFERENCE_KEY,
        String(configPanelCollapsed),
      );
    } catch {
      // The panel still works for the current session when storage is unavailable.
    }
  }, [configPanelCollapsed, configPreferenceReady]);

  async function generateQuiz(event: FormEvent) {
    event.preventDefault();
    if (generationLock.current) return;
    generationLock.current = true;
    setQuizError(null);
    let latestPartialSession: QuizSession | null = null;

    try {
      const batches = batchQuizBlueprint(blueprint);
      const responses: AgentResponse[] = [];
      const nextQuestions: QuizQuestion[] = [];
      const sessionId = uid("quiz-session");
      const requestChapterId =
        linkToCurrentLecture && activeLecture
          ? activeLecture.chapterId
          : currentChapterId;
      for (let batchIndex = 0; batchIndex < batches.length; batchIndex += 1) {
        const batch = batches[batchIndex];
        setGenerationProgress(
          `正在生成第 ${batchIndex + 1}/${batches.length} 批 · 已完成 ${nextQuestions.length}/${blueprint.length} 题`,
        );
        const prompt = [
          `围绕“${topic}”生成本批 ${batch.length} 道岗位培训题，重点考查：${focus}。`,
          `这是总计 ${blueprint.length} 道题中的第 ${batchIndex + 1}/${batches.length} 批。`,
          "必须依据本次 RAG 证据，严格逐项执行下面的 JSON 蓝图；返回顺序与蓝图一致，不得少题、换题型、换能力维度或修改分值。",
          "题型按 single_choice、true_false、cloze、short_answer 分区生成。判断题题干必须是可判断真假的完整陈述句，只提供“正确/错误”两个选项，answer 必须为 A（正确）或 B（错误）。主观题必须返回 reference_answer 与 scoring_rubric.key_points。所有题返回内容有明确差异的简洁解析和详细解析。",
          `QUIZ_BLUEPRINT=${JSON.stringify(batch)}`,
        ].join("\n");
        const response = await runAgent(
          buildAgentRequest({
            userId,
            courseId: ACTIVE_COURSE_ID,
            chapterId: requestChapterId,
            prompt,
            contentType: "quiz",
            scores,
            profile,
            quizBlueprint: {
              question_count: batch.length,
              slots: batch.map((slot) => ({
                sequence: slot.sequence,
                question_type: slot.questionType,
                difficulty: slot.difficulty,
                points: slot.points,
                capability_dimension: slot.capabilityDimension,
                question_purpose: "chapter_core",
                related_gap_ids: [],
              })),
            },
          }),
        );
        assertSuccessfulAgentResponse(response, "Quiz");
        const generated = asQuizQuestions(response);
        if (generated.length < batch.length) {
          throw new Error(
            `中央调度器第 ${batchIndex + 1} 批只返回 ${generated.length}/${batch.length} 道有效题目，请重新生成`,
          );
        }
        responses.push(response);
        const savedQuiz = asRecord(asRecord(response.saved_outputs)?.quiz);
        const backendArtifactId = String(savedQuiz?.artifact_id || "").trim();
        nextQuestions.push(
          ...batch.map((slot, index) => {
            const generatedQuestion = generated[index];
            const rawQuestion = asRecord(generatedQuestion);
            return {
              ...applyBlueprintToQuestion(generatedQuestion, slot),
              backend_artifact_id: backendArtifactId || undefined,
              backend_question_id:
                String(rawQuestion?.question_id || rawQuestion?.id || rawQuestion?.sequence || slot.sequence) ||
                undefined,
            };
          }),
        );
        const partialResponse = mergeQuizResponses(responses, nextQuestions);
        const basePartialSession = createQuizSession({
          id: sessionId,
          courseId: ACTIVE_COURSE_ID,
          chapterId: requestChapterId,
          topic,
          focus,
          difficulty:
            difficulty === "hard"
              ? "hard"
              : difficulty === "medium"
                ? "medium"
                : "easy",
          questions: nextQuestions,
          response: partialResponse,
          assessmentLink:
            linkToCurrentLecture && activeLecture
              ? {
                  lectureId: activeLecture.id,
                  chapterId: activeLecture.chapterId,
                  objectiveIds: activeLecture.targetDimensions.map(
                    (dimension) => `${activeLecture.chapterId}:${dimension}`,
                  ),
                }
              : null,
        });
        const partialSession: QuizSession = {
          ...basePartialSession,
          generationStatus:
            nextQuestions.length < blueprint.length ? "generating" : "complete",
          expectedQuestionCount: blueprint.length,
          generationError: "",
        };
        latestPartialSession = partialSession;
        onSessionChange(partialSession);
        onActiveSessionChange(sessionId);
        setPanel("current");
        setGenerationProgress(
          nextQuestions.length < blueprint.length
            ? `已生成 ${nextQuestions.length}/${blueprint.length} 题，继续生成下一批…`
            : `已生成全部 ${blueprint.length} 题，正在保存…`,
        );
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "无法连接中央调度器，请先接入后端接口";
      const preserved = latestPartialSession;
      if (preserved) {
        onSessionChange({
          ...preserved,
          generationStatus: "failed",
          generationError: message,
          updatedAt: new Date().toISOString(),
        });
      }
      setQuizError(
        preserved
          ? `${message}。已保留 ${preserved.questions.length}/${preserved.expectedQuestionCount} 道成功生成的题目`
          : message,
      );
    } finally {
      generationLock.current = false;
      setGenerationProgress("");
    }
  }

  const index = activeSession?.currentIndex ?? 0;
  const question = activeSession?.questions[index];
  const currentAnswer = question ? quizAnswerKey(question) : "";
  const response = question ? activeSession?.responses[question.id] : undefined;
  const selectedAnswer = response?.selectedAnswer;
  const isSubmitted = !!response?.submittedAt;
  const progress = activeSession
    ? quizSessionProgress(activeSession)
    : { submitted: 0, total: 0, correct: 0, accuracy: null };

  function updateActive(transform: (session: QuizSession) => QuizSession) {
    if (!activeSession) return null;
    const next = transform(activeSession);
    onSessionChange(next);
    return next;
  }

  function selectAnswer(answer: string) {
    if (!question) return;
    setQuizError(null);
    updateActive((session) => updateQuizDraft(session, question.id, answer));
  }

  function moveToQuestion(nextIndex: number) {
    setQuizError(null);
    updateActive((session) => setQuizCurrentIndex(session, nextIndex));
  }

  async function submitAnswer() {
    if (!selectedAnswer || !question || !activeSession) return;
    setQuizError(null);
    let grading;
    if (isSubjectiveQuizQuestion(question)) {
      setGradingQuestionId(question.id);
      try {
        grading = await gradeSubjectiveQuizAnswer({
          question,
          userAnswer: selectedAnswer,
          userId,
          courseId: ACTIVE_COURSE_ID,
        });
      } catch (error) {
        setQuizError(error instanceof Error ? error.message : "主观题评分失败");
        return;
      } finally {
        setGradingQuestionId("");
      }
    }
    const next = submitQuizAnswer(activeSession, question.id, grading);
    if (next === activeSession) return;
    onSessionChange(next);
    onQuestionSubmitted(next, question.id);
    if (next.status === "completed" && activeSession.status !== "completed") {
      void onFinished(next);
    }
  }

  return (
    <div className="section-scroll quiz-section">
      <div className="section-container quiz-section-container">
        <div className="section-intro">
          <div>
            <h2>生成个性化 Quiz</h2>
            <p>
              配置测验目标后，前端会以 content_type=quiz
              向中央调度器发起请求。题目、作答进度和知识来源会自动保存。
            </p>
          </div>
          <span className="orchestrator-badge">画像水平 · {profile.level}</span>
        </div>
        <div
          className={`quiz-grid ${configPanelCollapsed ? "config-panel-collapsed" : ""}`}
        >
          {configPanelVisible && (
          <form
            className={`card config-card ${configPanelCollapsed ? "overlay" : ""}`}
            onSubmit={generateQuiz}
            onMouseLeave={() => {
              if (configPanelCollapsed) setConfigPanelPeek(false);
            }}
          >
            <div className="config-card-header">
              <div>
                <span className="eyebrow">个性化测验</span>
                <h3 className="card-title">生成设置</h3>
              </div>
              <div className="config-card-actions">
                <span className="config-count-chip">{blueprintSummary.total} 题</span>
                <button
                  type="button"
                  className="panel-collapse-button quiz-config-collapse"
                  aria-label={
                    configPanelCollapsed ? "固定展开题目生成设置" : "隐藏题目生成设置"
                  }
                  title={
                    configPanelCollapsed ? "固定展开题目生成设置" : "隐藏题目生成设置"
                  }
                  onClick={() => {
                    if (configPanelCollapsed) {
                      setConfigPanelCollapsed(false);
                    } else {
                      setConfigPanelCollapsed(true);
                    }
                    setConfigPanelPeek(false);
                  }}
                >
                  <span className="panel-collapse-icon" aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className="form-field">
              <label htmlFor="quiz-topic">主题或知识点</label>
              <input
                id="quiz-topic"
                className="input"
                value={topic}
                onChange={(event) => {
                  setTopicOverride(event.target.value);
                }}
              />
            </div>
            {activeLecture && (
              <label className="assessment-link-toggle">
                <input
                  type="checkbox"
                  checked={linkToCurrentLecture}
                  onChange={(event) => setLinkToCurrentLecture(event.target.checked)}
                />
                <span>
                  <strong>用于评估当前讲义</strong>
                  <small>
                    精确关联 {activeLecture.chapterId}「{activeLecture.title}」；只有关联后的作答才更新该讲义掌握度。
                  </small>
                </span>
              </label>
            )}
            <div className="quiz-recommendations">
              <div className="quiz-recommendations-head">
                <span>Memory 推荐主题</span>
              </div>
              <div className="quiz-recommendation-list">
                {recommendations.quizOptions.map((option) => (
                  <button
                    type="button"
                    key={option.id}
                    className={`quiz-recommendation-chip ${
                      topic === option.topic ? "active" : ""
                    }`}
                    title={option.reason}
                    onClick={() => {
                      setTopicOverride(option.topic);
                      setFocusOverride(option.focus);
                    }}
                  >
                    <strong>{option.topic}</strong>
                  </button>
                ))}
              </div>
            </div>
            <div className="quiz-compact-fields">
              <div className="form-field">
                <label htmlFor="quiz-count">题目数量</label>
                <input
                  type="number"
                  id="quiz-count"
                  className="input"
                  min={MIN_QUIZ_QUESTION_COUNT}
                  max={MAX_QUIZ_QUESTION_COUNT}
                  value={count}
                  onChange={(event) => setCount(event.target.value)}
                  onBlur={() => setCount(String(normalizeQuizCount(count)))}
                />
              </div>
              <div className="form-field">
                <label htmlFor="quiz-difficulty">难度</label>
                <select
                  id="quiz-difficulty"
                  className="select"
                  value={difficulty}
                  onChange={(event) => setDifficultyOverride(event.target.value)}
                >
                  <option value="easy">基础</option>
                  <option value="medium">中等</option>
                  <option value="hard">进阶</option>
                </select>
              </div>
            </div>
            <div className="form-field">
              <label htmlFor="quiz-focus">考查重点（可选）</label>
              <textarea
                id="quiz-focus"
                className="input"
                value={focus}
                onChange={(event) => {
                  setFocusOverride(event.target.value);
                }}
              />
            </div>
            <div className="quiz-config-footer">
              <span>自动覆盖四类题型与八维岗位能力</span>
              <button
                type="submit"
                className="primary-button quiz-generate-button"
                disabled={busy || generationRunning || !topic.trim()}
                data-testid="quiz-generate"
              >
                {generationProgress ||
                  (generationRunning
                    ? "题目正在生成…"
                    : busy
                      ? "中央调度器处理中…"
                      : `生成 ${blueprintSummary.total} 题 Quiz →`)}
              </button>
            </div>
          </form>
          )}
          {configPanelCollapsed && (
            <button
              type="button"
              className="history-edge-trigger quiz-config-edge-trigger"
              aria-label="显示题目生成设置"
              title="显示题目生成设置"
              onMouseEnter={() => setConfigPanelPeek(true)}
              onFocus={() => setConfigPanelPeek(true)}
              onClick={() => setConfigPanelCollapsed(false)}
            >
              <span aria-hidden="true" />
            </button>
          )}
          <section className="card quiz-result-card">
            <div className="quiz-panel-tabs" role="tablist" aria-label="Quiz 视图">
              <button
                type="button"
                role="tab"
                aria-selected={panel === "current"}
                className={panel === "current" ? "active" : ""}
                onClick={() => setPanel("current")}
              >
                当前测验
                {activeSession && (
                  <span>{progress.submitted}/{progress.total}</span>
                )}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={panel === "history"}
                className={panel === "history" ? "active" : ""}
                onClick={() => setPanel("history")}
              >
                历史记录 <span>{sessions.length}</span>
              </button>
            </div>
            {panel === "history" ? (
              <QuizHistoryPanel
                sessions={sessions}
                onOpen={(sessionId) => {
                  onActiveSessionChange(sessionId);
                  setPanel("current");
                }}
              />
            ) : !question || !activeSession ? (
              <div
                className={`quiz-empty ${displayedQuizError ? "has-error" : ""} ${
                  generationRunning ? "is-generating" : ""
                }`}
                aria-live="polite"
              >
                <div>
                  <span className="quiz-empty-symbol">测</span>
                  <strong>
                    {displayedQuizError
                      ? "Quiz 暂不可用"
                      : generationRunning
                        ? "知链正在生成题目"
                        : "等待后端生成测验"}
                  </strong>
                  <p>
                    {displayedQuizError ||
                      generationProgress ||
                      (generationRunning
                        ? `已生成 ${activeSession?.questions.length || 0}/${activeSession?.expectedQuestionCount || blueprint.length} 题，正在继续生成…`
                        : "") ||
                      "完成左侧设置并生成 Quiz。生成后会立即保存，刷新页面也能继续作答。"}
                  </p>
                </div>
              </div>
            ) : (
              <>
                <QuizQuestionOverview
                  session={activeSession}
                  onOpen={moveToQuestion}
                />
                {generationRunning && (
                  <div className="quiz-generation-banner" role="status" aria-live="polite">
                    <span className="quiz-generation-spinner" aria-hidden="true" />
                    <div>
                      <strong>题目正在分批生成</strong>
                      <span>
                        {generationProgress ||
                          `已生成 ${activeSession.questions.length}/${activeSession.expectedQuestionCount} 题，正在继续生成…`}
                      </span>
                    </div>
                  </div>
                )}
                <div className="quiz-topline">
                  <div>
                    <span className="quiz-counter">
                      第 {index + 1} 题 / 共 {activeSession.questions.length} 题
                    </span>
                    <span className={`quiz-session-status ${activeSession.status}`}>
                      {activeSession.status === "completed" ? "已完成" : "自动保存中"}
                    </span>
                  </div>
                  <div className="quiz-source-summary">
                    {!!activeSession.retrieval.sourceRefs.length && (
                      <span>{activeSession.retrieval.sourceRefs.length} 个知识来源</span>
                    )}
                    <span className="difficulty-chip">
                      {QUIZ_TYPE_LABELS[quizQuestionType(question)]} · {QUIZ_DIFFICULTY_LABELS[
                        question.difficulty === "hard"
                          ? "hard"
                          : question.difficulty === "medium"
                            ? "medium"
                            : "easy"
                      ]} · {quizQuestionPoints(question)} 分
                    </span>
                  </div>
                </div>
                <h3 className="quiz-question">{question.stem}</h3>
                {isSubjectiveQuizQuestion(question) ? (
                  <div className="subjective-answer-field">
                    <label htmlFor={`answer-${question.id}`}>你的答案</label>
                    <textarea
                      id={`answer-${question.id}`}
                      className="input"
                      rows={quizQuestionType(question) === "short_answer" ? 7 : 4}
                      value={selectedAnswer || ""}
                      disabled={
                        isSubmitted ||
                        generationRunning ||
                        gradingQuestionId === question.id
                      }
                      placeholder={
                        quizQuestionType(question) === "cloze"
                          ? "填写被挖空的核心概念，可使用等价表述"
                          : "按要点作答，说明原理、步骤或判断依据"
                      }
                      onChange={(event) => selectAnswer(event.target.value)}
                    />
                    <small>提交后由中央评分 Agent 结合评分点、语义向量和安全规则给出部分分。</small>
                  </div>
                ) : (
                  <div
                    className={`option-list ${
                      quizQuestionType(question) === "true_false" ? "true-false-list" : ""
                    }`}
                    role={quizQuestionType(question) === "true_false" ? "radiogroup" : undefined}
                    aria-label={quizQuestionType(question) === "true_false" ? "选择正确或错误" : undefined}
                  >
                    {question.options.map((option, optionIndex) => {
                      const key = String.fromCharCode(65 + optionIndex);
                      const isTrueFalse = quizQuestionType(question) === "true_false";
                      const state = isSubmitted
                        ? key === currentAnswer
                          ? "correct"
                          : key === selectedAnswer
                            ? "wrong"
                            : ""
                        : selectedAnswer === key
                          ? "selected"
                          : "";
                      return (
                        <button
                          type="button"
                          className={`option-button ${state}`}
                          role={isTrueFalse ? "radio" : undefined}
                          aria-checked={isTrueFalse ? selectedAnswer === key : undefined}
                          key={`${key}-${option}`}
                          disabled={isSubmitted || generationRunning}
                          onClick={() => selectAnswer(key)}
                        >
                          <span className="option-key">
                            {isTrueFalse ? (optionIndex === 0 ? "✓" : "×") : key}
                          </span>
                          <span>{option}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {isSubmitted && (
                  <div className="explanation">
                    <div className="explanation-heading">
                      <strong>
                        {isSubjectiveQuizQuestion(question)
                          ? `得分 ${response?.earnedPoints ?? 0}/${response?.possiblePoints ?? quizQuestionPoints(question)}`
                          : selectedAnswer === currentAnswer
                            ? "回答正确。"
                            : `正确答案：${currentAnswer}。`}
                      </strong>
                      <div className="explanation-mode" role="group" aria-label="解析详细程度">
                        <button
                          type="button"
                          className={activeSession.explanationMode === "concise" ? "active" : ""}
                          aria-pressed={activeSession.explanationMode === "concise"}
                          onClick={() =>
                            updateActive((session) => setQuizExplanationMode(session, "concise"))
                          }
                        >
                          简洁解析
                        </button>
                        <button
                          type="button"
                          className={activeSession.explanationMode === "detailed" ? "active" : ""}
                          aria-pressed={activeSession.explanationMode === "detailed"}
                          onClick={() =>
                            updateActive((session) => setQuizExplanationMode(session, "detailed"))
                          }
                        >
                          详细解析
                        </button>
                      </div>
                    </div>
                    <div className="explanation-content" aria-live="polite">
                      <MarkdownContent
                        content={quizExplanationText(
                          question,
                          activeSession.explanationMode,
                        )}
                      />
                    </div>
                    {response?.feedback && (
                      <div className={`grading-feedback ${response.safetyCriticalError ? "critical" : ""}`}>
                        <strong>评分反馈</strong>
                        <span>{response.feedback}</span>
                        {response.safetyCriticalError && (
                          <span className="grading-critical-note">
                            检测到安全红线错误：本题已执行安全封顶，并阻止岗位阶段达标。
                          </span>
                        )}
                        {!!response.contradictions.length && (
                          <span>需复核的矛盾：{response.contradictions.join("；")}</span>
                        )}
                        <small>
                          {response.gradingMethod}
                          {response.semanticSimilarity !== null
                            ? ` · 语义相似度 ${Math.round(response.semanticSimilarity * 100)}%`
                            : ""}
                          {response.keyPointCoverage !== null
                            ? ` · 评分点覆盖 ${Math.round(response.keyPointCoverage * 100)}%`
                            : ""}
                        </small>
                      </div>
                    )}
                    {!!question.source_refs?.length && (
                      <div className="quiz-evidence-refs">
                        依据：{question.source_refs.slice(0, 3).join("、")}
                      </div>
                    )}
                  </div>
                )}
                {displayedQuizError && (
                  <div className="quiz-inline-error" role="alert" aria-live="assertive">
                    <strong>Quiz 操作未完成</strong>
                    <span>{displayedQuizError}</span>
                    <small>已生成内容和作答草稿均会保留，解决后可直接重试。</small>
                  </div>
                )}
                <div className="quiz-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={index === 0}
                    onClick={() => moveToQuestion(index - 1)}
                  >
                    上一题
                  </button>
                  {!isSubmitted ? (
                    <button
                      type="button"
                      className="primary-button"
                      disabled={
                        !selectedAnswer?.trim() ||
                        generationRunning ||
                        gradingQuestionId === question.id
                      }
                      onClick={() => void submitAnswer()}
                    >
                      {gradingQuestionId === question.id ? "语义评分中…" : "提交答案"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="primary-button"
                      disabled={index === activeSession.questions.length - 1}
                      onClick={() => moveToQuestion(index + 1)}
                    >
                      {index === activeSession.questions.length - 1
                        ? activeSession.status === "completed"
                          ? "测验已完成"
                          : "等待完成"
                        : "下一题"}
                    </button>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function QuizHistoryPanel({
  sessions,
  onOpen,
}: {
  sessions: QuizSession[];
  onOpen: (sessionId: string) => void;
}) {
  if (!sessions.length) {
    return (
      <div className="quiz-history-empty">
        <span>暂无 Quiz 记录</span>
        <p>新生成的题目会在后端返回后立即保存，未完成的测验也可以继续。</p>
      </div>
    );
  }

  return (
    <div className="quiz-history-panel">
      <div className="quiz-history-heading">
        <div>
          <strong>Quiz 历史</strong>
          <p>保留最近 50 次测验的题目、答案、解析和知识来源。</p>
        </div>
      </div>
      <div className="quiz-history-list">
        {sessions.map((session) => {
          const progress = quizSessionProgress(session);
          const createdAt = new Date(session.createdAt);
          const dateLabel = Number.isFinite(createdAt.getTime())
            ? createdAt.toLocaleString("zh-CN", {
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })
            : session.createdAt;
          return (
            <article className="quiz-history-item" key={session.id}>
              <div className="quiz-history-item-main">
                <div className="quiz-history-title-row">
                  <strong>{session.topic}</strong>
                  <span className={`quiz-session-status ${session.status}`}>
                    {session.status === "completed"
                      ? "已完成"
                      : session.status === "abandoned"
                        ? "已暂停"
                        : "进行中"}
                  </span>
                </div>
                <p>{session.focus || "综合知识测验"}</p>
                <div className="quiz-history-meta">
                  <span>{dateLabel}</span>
                  <span>
                    {progress.submitted}/{progress.total} 题已提交
                  </span>
                  {progress.accuracy !== null && (
                    <span>
                      当前得分 {progress.earnedPoints}/{progress.possiblePoints}（
                      {Math.round(progress.accuracy * 100)}%）
                    </span>
                  )}
                  {!!session.retrieval.sourceRefs.length && (
                    <span>{session.retrieval.sourceRefs.length} 个知识来源</span>
                  )}
                </div>
              </div>
              <button
                type="button"
                className="secondary-button"
                onClick={() => onOpen(session.id)}
              >
                {session.status === "completed" ? "查看结果" : "继续作答"}
              </button>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function QuizQuestionOverview({
  session,
  onOpen,
}: {
  session: QuizSession;
  onOpen: (index: number) => void;
}) {
  const groups = (Object.keys(QUIZ_TYPE_LABELS) as QuizQuestionType[]).map(
    (type) => ({
      type,
      questions: session.questions
        .map((question, index) => ({ question, index }))
        .filter((item) => quizQuestionType(item.question) === type),
    }),
  );
  return (
    <div className="quiz-overview">
      <div className="quiz-overview-heading">
        <strong>题目概览</strong>
        <span>按题型归类，点击题号跳转</span>
      </div>
      <div className="quiz-overview-groups">
        {groups.map((group) => (
          <div className="quiz-overview-group" key={group.type}>
            <span>{QUIZ_TYPE_LABELS[group.type]}</span>
            <div>
              {group.questions.map(({ question, index }) => {
                const response = session.responses[question.id];
                const status = response?.submittedAt
                  ? response.isCorrect
                    ? "correct"
                    : "wrong"
                  : response?.selectedAnswer
                    ? "draft"
                    : "";
                return (
                  <button
                    type="button"
                    className={`${status} ${index === session.currentIndex ? "active" : ""}`}
                    aria-label={`跳转到第 ${index + 1} 题`}
                    aria-current={index === session.currentIndex ? "step" : undefined}
                    key={question.id}
                    onClick={() => onOpen(index)}
                  >
                    {index + 1}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function nextBackendLearningPathChapter(
  learningPath: UserLearningPath | null,
  chapterId: string,
): { id: string; title: string } | null {
  if (!learningPath?.chapters.length) return nextCourseChapter(chapterId);
  const ordered = [...learningPath.chapters].sort(
    (left, right) => left.chapter_order - right.chapter_order,
  );
  const currentIndex = ordered.findIndex(
    (chapter) => chapter.chapter_id === chapterId,
  );
  const explicitNextId =
    currentIndex >= 0 ? ordered[currentIndex].next_chapter_id : null;
  const next = explicitNextId
    ? ordered.find((chapter) => chapter.chapter_id === explicitNextId)
    : currentIndex >= 0
      ? ordered[currentIndex + 1]
      : undefined;
  return next
    ? { id: next.chapter_id, title: next.chapter_title }
    : null;
}

function LectureView({
  userId,
  sessions,
  activeSessionId,
  onActiveSessionChange,
  onSessionCreated,
  profile,
  scores,
  progress,
  learningPath,
  capabilityEvidence,
  busy,
  runAgent,
  onProgressChanged,
}: {
  userId: string;
  sessions: LectureSession[];
  activeSessionId: string;
  onActiveSessionChange: (sessionId: string) => void;
  onSessionCreated: (session: LectureSession) => void;
  profile: LearnerProfile;
  scores: ScoreMap;
  progress: LearningProgressResult;
  learningPath: UserLearningPath | null;
  capabilityEvidence: CapabilityEvidence[];
  busy: boolean;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  onProgressChanged: () => void | Promise<void>;
}) {
  const [lectureError, setLectureError] = useState("");
  const [confirmNext, setConfirmNext] = useState(false);
  const [generationState, setGenerationState] = useState<{
    reason: LectureGenerationReason;
    chapterId: string;
  } | null>(null);
  const backendChaptersById = useMemo(
    () =>
      new Map(
        learningPath?.chapters.map((chapter) => [
          chapter.chapter_id,
          chapter.chapter_title.trim(),
        ]) ?? [],
      ),
    [learningPath],
  );
  const hasBackendPath = backendChaptersById.size > 0;
  const validSessions = useMemo(
    () =>
      hasBackendPath
        ? sessions.filter(
            (session) =>
              backendChaptersById.get(session.chapterId) ===
              session.chapterTitle.trim(),
          )
        : sessions,
    [backendChaptersById, hasBackendPath, sessions],
  );
  const legacySessions = useMemo(
    () =>
      hasBackendPath
        ? sessions.filter(
            (session) =>
              backendChaptersById.get(session.chapterId) !==
              session.chapterTitle.trim(),
          )
        : [],
    [backendChaptersById, hasBackendPath, sessions],
  );
  const currentChapterId =
    learningPath?.current_chapter_id ||
    progress.currentChapterId ||
    ACTIVE_CHAPTER_ID;
  const currentPathChapter = learningPath?.chapters.find(
    (chapter) => chapter.chapter_id === currentChapterId,
  );
  const selectedLecture = validSessions.find(
    (session) => session.id === activeSessionId,
  );
  const currentChapterLecture = validSessions.find(
    (session) => session.chapterId === currentChapterId,
  );
  const activeLecture = selectedLecture ?? currentChapterLecture ?? null;
  const lectureGenerating = generationState !== null;

  useEffect(() => {
    const resolvedId = activeLecture?.id ?? "";
    if (resolvedId !== activeSessionId) onActiveSessionChange(resolvedId);
  }, [activeLecture?.id, activeSessionId, onActiveSessionChange]);
  const mastery = useMemo(
    () =>
      activeLecture
        ? calculateLectureMastery(activeLecture, capabilityEvidence)
        : null,
    [activeLecture, capabilityEvidence],
  );
  const nextChapter = activeLecture
    ? nextBackendLearningPathChapter(learningPath, activeLecture.chapterId)
    : null;

  async function requestLecture(
    reason: LectureGenerationReason,
    chapterId: string,
    predecessor: LectureSession | null,
  ) {
    setLectureError("");
    const pathChapter = learningPath?.chapters.find(
      (chapter) => chapter.chapter_id === chapterId,
    );
    const chapterTitle =
      (reason === "next_stage"
        ? nextBackendLearningPathChapter(learningPath, chapterId)?.title
        : pathChapter?.chapter_title) ||
      predecessor?.chapterTitle ||
      progress.currentChapterTitle;
    const prompt = [
      `请为当前学习者生成“${chapterId} ${chapterTitle}”阶段学习讲义。`,
      `学习者背景：${profile.background}；表达偏好：${profile.preference}。`,
      `当前岗位成长阶段：${progress.currentStageLabel}，综合进度 ${progress.overallProgress}%。`,
      `当前主要缺口：${progress.blockers.slice(0, 4).join("；") || "暂无明确缺口"}。`,
      "必须依据本次 RAG 检索证据，按学习目标、核心概念、原理、易错点、安全边界和小结组织；不得凭空补充设备参数或危险操作。",
    ].join("\n");
    const contentType = reason === "next_stage" ? "next_step" : "lecture";
    let response = await runAgent(
      buildAgentRequest({
        userId,
        courseId: ACTIVE_COURSE_ID,
        chapterId,
        prompt,
        contentType,
        scores,
        profile,
        learningProgress: progress.agentContext,
      }),
    );
    const targetChapter =
      reason === "next_stage"
        ? nextBackendLearningPathChapter(learningPath, chapterId)
        : null;
    const targetChapterId = targetChapter?.id ?? chapterId;
    const targetChapterTitle =
      targetChapter?.title ||
      learningPath?.chapters.find(
        (chapter) => chapter.chapter_id === targetChapterId,
      )?.chapter_title;
    let session: LectureSession;
    try {
      session = createLectureSession({
        id: uid("lecture-session"),
        courseId: ACTIVE_COURSE_ID,
        chapterId: targetChapterId,
        chapterTitle: targetChapterTitle,
        response,
        capabilityEvidence,
        generationReason: reason,
        predecessorId: predecessor?.id,
      });
    } catch (error) {
      if (reason !== "next_stage") throw error;
      // Some teammate backends advance the chapter but return only progress
      // metadata. A second normal lecture request retrieves the advanced
      // chapter without inventing any local content.
      response = await runAgent(
        buildAgentRequest({
          userId,
          courseId: ACTIVE_COURSE_ID,
          chapterId: targetChapterId,
          prompt: prompt.replace(chapterId, targetChapterId),
          contentType: "lecture",
          scores,
          profile,
          learningProgress: progress.agentContext,
        }),
      );
      session = createLectureSession({
        id: uid("lecture-session"),
        courseId: ACTIVE_COURSE_ID,
        chapterId: targetChapterId,
        chapterTitle: targetChapterTitle,
        response,
        capabilityEvidence,
        generationReason: reason,
        predecessorId: predecessor?.id,
      });
    }
    onSessionCreated(session);
    if (reason === "next_stage") await onProgressChanged();
  }

  async function generate(
    reason: LectureGenerationReason,
    chapterId: string,
    predecessor: LectureSession | null,
  ) {
    if (lectureGenerating) return;
    setGenerationState({ reason, chapterId });
    try {
      await requestLecture(reason, chapterId, predecessor);
    } catch (error) {
      setLectureError(
        error instanceof Error ? error.message : "学习讲义生成失败，请检查中央调度器",
      );
    } finally {
      setGenerationState(null);
    }
  }

  function requestNextStage() {
    if (!activeLecture || !nextChapter || busy || lectureGenerating) return;
    if (!mastery?.recommendedForNextStage) {
      setConfirmNext(true);
      return;
    }
    void generate("next_stage", activeLecture.chapterId, activeLecture);
  }

  return (
    <div className="lecture-page">
      <aside className="lecture-library card">
        <div className="lecture-library-head">
          <div>
            <h2>讲义记录</h2>
            <p>已生成的讲义会自动保存</p>
          </div>
          <span>{validSessions.length}</span>
        </div>
        <div className="lecture-history-list">
          {validSessions.length ? (
            validSessions.map((lecture) => {
              const itemMastery = calculateLectureMastery(
                lecture,
                capabilityEvidence,
              );
              return (
                <button
                  type="button"
                  className={`lecture-history-item ${lecture.id === activeLecture?.id ? "active" : ""}`}
                  key={lecture.id}
                  onClick={() => onActiveSessionChange(lecture.id)}
                >
                  <span className="lecture-history-chapter">{lecture.chapterId}</span>
                  <strong>{lecture.title}</strong>
                  <small>
                    {itemMastery.status === "mastered"
                      ? "已掌握"
                      : itemMastery.score !== null
                        ? `掌握度 ${itemMastery.score}%`
                        : itemMastery.observedScore !== null
                          ? `练习表现 ${itemMastery.observedScore}% · 证据不足`
                          : "待评估"}
                  </small>
                </button>
              );
            })
          ) : (
            <div className="lecture-history-empty">生成第一份讲义后，这里会形成个人讲义库。</div>
          )}
          {legacySessions.length > 0 && (
            <div className="lecture-legacy-note">
              已保留并隐藏 {legacySessions.length} 条旧目录讲义，避免其干扰当前学习路径。
            </div>
          )}
        </div>
      </aside>

      <section className="lecture-reader card">
        {!activeLecture ? (
          <div className="lecture-empty">
            <span>学</span>
            <h2>从当前阶段开始学习</h2>
            <p>
              知链将依据你的 Memory、岗位学习进度和 RAG 知识库，生成章节
              {currentChapterId}「
              {currentPathChapter?.chapter_title || progress.currentChapterTitle}
              」讲义。
            </p>
            <button
              type="button"
              className="primary-button"
              disabled={busy || lectureGenerating}
              onClick={() =>
                void generate("initial", currentChapterId, null)
              }
            >
              {lectureGenerating ? "中央调度器生成中…" : "生成当前阶段讲义"}
            </button>
            {lectureGenerating && (
              <p className="lecture-generation-status">
                正在检索章节资料并执行多 Agent 生成与核验，通常需要 1–2 分钟，请勿重复点击。
              </p>
            )}
            {lectureError && <p className="inline-error">{lectureError}</p>}
          </div>
        ) : (
          <>
            <header className="lecture-reader-head">
              <div>
                <div className="lecture-meta-row">
                  <span>章节 {activeLecture.chapterId}</span>
                  <span>{activeLecture.chapterTitle}</span>
                  <span>{activeLecture.sourceRefs.length} 个知识来源</span>
                </div>
                <h2>{activeLecture.title}</h2>
                <p>{activeLecture.summary}</p>
              </div>
              <div className="lecture-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy || lectureGenerating}
                  onClick={() =>
                    void generate(
                      "regenerate",
                      activeLecture.chapterId,
                      activeLecture,
                    )
                  }
                >
                  {generationState?.reason === "regenerate"
                    ? "正在重新生成…"
                    : "重新生成"}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={busy || lectureGenerating || !nextChapter}
                  onClick={requestNextStage}
                >
                  {generationState?.reason === "next_stage"
                    ? "正在生成下阶段…"
                    : nextChapter
                      ? "生成下阶段讲义"
                      : "已是最后阶段"}
                </button>
                {lectureGenerating && (
                  <p className="lecture-generation-status">
                    正在检索章节资料并执行多 Agent 生成与核验，通常需要 1–2 分钟，请勿重复点击。
                  </p>
                )}
                {mastery && (
                  <p className={mastery.recommendedForNextStage ? "ready" : "hold"}>
                    {mastery.message}
                  </p>
                )}
              </div>
            </header>
            {lectureError && <p className="lecture-error">{lectureError}</p>}
            <div className="lecture-reader-body">
              <div className="lecture-content">
                {activeLecture.sections.map((section, index) => (
                  <article key={`${section.heading}-${index}`}>
                    <h3>{section.heading}</h3>
                    <MarkdownContent content={section.content} />
                  </article>
                ))}
              </div>
              <aside className="lecture-mastery-panel">
                <div className="lecture-mastery-score">
                  <span>
                    {mastery?.score !== null && mastery?.score !== undefined
                      ? `${mastery.score}%`
                      : "待评估"}
                  </span>
                  <small>当前讲义掌握度</small>
                </div>
                <div className="lecture-mastery-track">
                  <span style={{ width: `${mastery?.score ?? 0}%` }} />
                </div>
                <p>
                  {mastery?.observedScore !== null && mastery?.observedScore !== undefined
                    ? `已关联作答的观察表现 ${mastery.observedScore}%，评价可信度 ${Math.round(mastery.confidence * 100)}%。`
                    : "只统计与本讲义、章节和学习目标精确关联的新证据。"}
                </p>
                <div className="lecture-requirements">
                  {mastery?.requirements.map((requirement) => (
                    <div className={requirement.passed ? "passed" : "pending"} key={requirement.label}>
                      <span>{requirement.passed ? "✓" : "·"}</span>
                      <div>
                        <strong>{requirement.label}</strong>
                        <small>{requirement.current} / {requirement.requirement}</small>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="lecture-sources">
                  <strong>RAG 知识依据</strong>
                  {activeLecture.sourceRefs.length ? (
                    activeLecture.sourceRefs.slice(0, 6).map((source) => (
                      <span title={source} key={source}>{source.split(/[\\/]/).pop()}</span>
                    ))
                  ) : (
                    <span>本次返回未包含可展示的来源名称</span>
                  )}
                </div>
              </aside>
            </div>
          </>
        )}
      </section>

      {confirmNext && activeLecture && nextChapter && (
        <div className="confirmation-backdrop" role="presentation" onMouseDown={() => setConfirmNext(false)}>
          <div
            className="confirmation-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="lecture-confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="confirmation-symbol">!</span>
            <h2 id="lecture-confirm-title">当前知识尚未达到推荐掌握度</h2>
            <p>
              {mastery?.message}。如果继续，将进入章节 {nextChapter.id}「{nextChapter.title}」，
              当前讲义仍会保留在历史记录中。
            </p>
            <div className="confirmation-actions">
              <button type="button" onClick={() => setConfirmNext(false)}>继续巩固</button>
              <button
                type="button"
                className="danger-confirm"
                onClick={() => {
                  setConfirmNext(false);
                  void generate("next_stage", activeLecture.chapterId, activeLecture);
                }}
              >
                仍然生成下阶段讲义
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

type RadarMetric = {
  id: string;
  label: string;
  value: number;
  displayValue: string;
};

function boundedPercent(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

function firstNumber(value: string): number | null {
  const match = value.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function gateCompletion(gate: ProgressGate): number {
  if (gate.passed) return 100;
  const current = firstNumber(gate.current);
  const requirement = firstNumber(gate.requirement);
  if (current === null || requirement === null || requirement <= 0) return 0;
  return boundedPercent((current / requirement) * 100);
}

function stageGateRadarItems(gates: ProgressGate[]): RadarMetric[] {
  const mapped = gates.map((gate) => ({
    id: gate.id,
    label: gate.label,
    value: gateCompletion(gate),
    displayValue: gate.passed ? "已达标" : `${Math.round(gateCompletion(gate))}%`,
  }));
  const core =
    mapped.length > 8
      ? [
          ...mapped.slice(0, 7),
          {
            id: "combined-evidence-gates",
            label: "证据完备",
            value: Math.min(...mapped.slice(7).map((item) => item.value)),
            displayValue: `${mapped.slice(7).filter((item) => item.value >= 100).length}/${mapped.slice(7).length} 项`,
          },
        ]
      : [...mapped];
  if (!core.length) {
    return Array.from({ length: 8 }, (_, index) => ({
      id: `empty-gate-${index}`,
      label: "",
      value: 0,
      displayValue: "",
    }));
  }
  const sources = [...core];
  let repeatIndex = 0;
  while (core.length < 8) {
    const source = sources[repeatIndex % sources.length];
    core.push({
      ...source,
      id: `${source.id}-repeat-${repeatIndex}`,
      label: "",
      displayValue: "",
    });
    repeatIndex += 1;
  }
  return core.slice(0, 8);
}

function radarVertex(value: number, index: number, radius = 44) {
  const angle = ((-90 + index * 45) * Math.PI) / 180;
  const scaledRadius = radius * (boundedPercent(value) / 100);
  return {
    x: 50 + Math.cos(angle) * scaledRadius,
    y: 50 + Math.sin(angle) * scaledRadius,
  };
}

function radarClipPath(items: RadarMetric[]): string {
  const points = items
    .slice(0, 8)
    .map((item, index) => {
      const point = radarVertex(item.value, index);
      return `${point.x}% ${point.y}%`;
    })
    .join(", ");
  return `polygon(${points})`;
}

function OctagonRadar({
  items,
  centerValue,
  centerLabel,
  ariaLabel,
  tone,
}: {
  items: RadarMetric[];
  centerValue: string;
  centerLabel: string;
  ariaLabel: string;
  tone: "gate" | "capability";
}) {
  return (
    <div className={`octagon-radar ${tone}`} role="img" aria-label={ariaLabel}>
      <div className="octagon-radar-plot">
        <div className="octagon-radar-grid" aria-hidden="true">
          {[1, 0.75, 0.5, 0.25].map((scale) => (
            <span
              className="octagon-grid-ring"
              key={scale}
              style={{ transform: `scale(${scale})` }}
            />
          ))}
          {[0, 45, 90, 135].map((angle) => (
            <span
              className="octagon-grid-spoke"
              key={angle}
              style={{ transform: `rotate(${angle}deg)` }}
            />
          ))}
          <span
            className="octagon-radar-fill"
            style={{ clipPath: radarClipPath(items) }}
          />
          {items.slice(0, 8).map((item, index) => {
            const point = radarVertex(item.value, index);
            return (
              <span
                className="octagon-radar-point"
                key={item.id}
                style={{ left: `${point.x}%`, top: `${point.y}%` }}
              />
            );
          })}
          <span className="octagon-radar-center">
            <strong>{centerValue}</strong>
            <small>{centerLabel}</small>
          </span>
        </div>
        {items.slice(0, 8).map((item, index) => {
          if (!item.label) return null;
          const angle = ((-90 + index * 45) * Math.PI) / 180;
          const position = {
            left: `${50 + Math.cos(angle) * 45}%`,
            top: `${50 + Math.sin(angle) * 45}%`,
          };
          return (
            <span className="octagon-radar-label" key={`${item.id}-label`} style={position}>
              <strong>{item.label}</strong>
              <small>{item.displayValue}</small>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function MoreInfoDrawer({
  userId,
  open,
  onClose,
  progress,
  profile,
  scores,
  busy,
  runAgent,
}: {
  userId: string;
  open: boolean;
  onClose: () => void;
  progress: LearningProgressResult;
  profile: LearnerProfile;
  scores: ScoreMap;
  busy: boolean;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
}) {
  const [nextPlan, setNextPlan] = useState("");
  const [planSources, setPlanSources] = useState<string[]>([]);
  const [planError, setPlanError] = useState("");

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  async function generateNextPlan() {
    setPlanError("");
    const prompt = [
      "请根据当前学习进度，为学习者生成一个可立即执行的下一步训练任务。",
      `当前阶段：${progress.currentStageLabel}。`,
      `当前章节：${progress.currentChapterId} ${progress.currentChapterTitle}。`,
      `主要阻塞项：${progress.blockers.join("；") || "暂无"}。`,
      "请从已接入的数控知识库检索依据，给出学习目标、训练步骤、完成标准和安全提醒；不要虚构实操考核结果。",
    ].join("\n");
    try {
      const response = await runAgent(
        buildAgentRequest({
          userId,
          courseId: ACTIVE_COURSE_ID,
          chapterId: progress.currentChapterId,
          prompt,
          contentType: "qa",
          scores,
          profile,
          learningProgress: progress.agentContext,
        }),
      );
      const payload = asQaPayload(response);
      setNextPlan(
        payload?.answer ||
          response.final_output?.summary ||
          "中央调度器已完成任务，但没有返回可展示的训练方案。",
      );
      setPlanSources(
        [
          ...(response.rag_package?.evidence ?? []).map(
            (item) => item.source_file ?? item.source_doc ?? "",
          ),
          ...(response.rag_package?.citations ?? []).map(
            (item) => item.source_file ?? item.source_doc ?? "",
          ),
        ]
          .filter(Boolean)
          .filter((value, index, values) => values.indexOf(value) === index)
          .slice(0, 5),
      );
    } catch (error) {
      setPlanError(
        error instanceof Error ? error.message : "下一步训练方案生成失败",
      );
    }
  }

  if (!open) return null;

  return (
    <div
      className="more-info-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <aside
        className="more-info-drawer"
        id="more-info-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="more-info-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="more-info-header">
          <div>
            <span>学习进度辅助信息</span>
            <h2 id="more-info-title">更多信息</h2>
          </div>
          <button type="button" aria-label="关闭更多信息" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="more-info-body">
          <section className="more-info-summary">
            <div>
              <span>当前阶段</span>
              <strong>{progress.currentStageLabel}</strong>
            </div>
            <div>
              <span>综合进度</span>
              <strong>{progress.overallProgress}%</strong>
            </div>
            <p>
              当前章节 {progress.currentChapterId}「{progress.currentChapterTitle}」
            </p>
          </section>

          <details className="more-info-section" open>
            <summary>
              <span>评价标准</span>
              <small>达标条件与八维能力规则</small>
            </summary>
            <div className="more-info-section-content">
              <h3>{progress.currentStageLabel} 达标条件</h3>
              <p className="more-info-explanation">
                每项条件单独判断；安全、实操和审核证据属于硬门槛，不能由其他高分抵消。
              </p>
              <div className="drawer-gate-list">
                {progress.gates.map((gate) => (
                  <div className={gate.passed ? "passed" : "pending"} key={gate.id}>
                    <span>{gate.passed ? "✓" : "!"}</span>
                    <div>
                      <strong>{gate.label}</strong>
                      <small>当前 {gate.current} · 要求 {gate.requirement}</small>
                    </div>
                  </div>
                ))}
              </div>

              <h3>八维岗位能力评分</h3>
              <div className="drawer-dimension-list">
                {progress.dimensions.map((dimension) => (
                  <div key={dimension.id}>
                    <span>{dimension.label}</span>
                    <strong>权重 {dimension.weight}%</strong>
                    <small>
                      {dimension.ratingStatus === "unassessed"
                        ? "待评估"
                        : dimension.ratingStatus === "insufficient"
                          ? `暂估 ${dimension.score ?? 0} 分`
                          : `${dimension.score ?? 0} 分`}
                    </small>
                  </div>
                ))}
              </div>
              <ul className="scoring-rule-list">
                <li>分数范围为0–100分，由客观测验、审核实操和外部考核证据计算。</li>
                <li>难度、时间衰减、证据来源和评分可信度共同影响证据权重。</li>
                <li>采用中性先验抑制小样本高分，重复题目不会反复提高能力评级。</li>
                <li>至少4条独立证据、3个知识点和2次独立测验后才可形成正式等级。</li>
              </ul>
            </div>
          </details>

          <details className="more-info-section">
            <summary>
              <span>评价证据概览</span>
              <small>数据来源与评级覆盖</small>
            </summary>
            <div className="more-info-section-content">
              <div className="drawer-evidence-grid">
                <div><strong>{progress.evidence.rawTraceCount}</strong><span>原始操作记录</span></div>
                <div><strong>{progress.evidence.effectiveEvidenceCount}</strong><span>独立有效证据</span></div>
                <div><strong>{progress.evidence.ratedDimensionCount}/8</strong><span>可评级维度</span></div>
                <div><strong>{progress.evidence.groundedEvidenceCount}</strong><span>RAG有依据</span></div>
              </div>
              <p className="more-info-explanation">
                Quiz {progress.evidence.quizEvidenceCount} 条 · 实操 {progress.evidence.practicalEvidenceCount} 条 ·
                外部考核 {progress.evidence.externalAssessmentCount} 条。
              </p>
            </div>
          </details>

          <details className="more-info-section" open>
            <summary>
              <span>下一步学习任务</span>
              <small>结合Memory、门槛与RAG生成</small>
            </summary>
            <div className="more-info-section-content">
              <div className="drawer-blocker-list">
                {(progress.blockers.length
                  ? progress.blockers
                  : ["当前阶段已达标，可进入下一阶段复核"]
                )
                  .slice(0, 4)
                  .map((blocker) => (
                    <p key={blocker}><span>→</span>{blocker}</p>
                  ))}
              </div>
              <button
                type="button"
                className="primary-button drawer-plan-button"
                disabled={busy}
                onClick={() => void generateNextPlan()}
              >
                {busy ? "中央调度器处理中…" : "生成下一步训练方案"}
              </button>
              {planError && <p className="inline-error">{planError}</p>}
              {nextPlan && (
                <div className="next-plan-result">
                  <MarkdownContent content={nextPlan} />
                  {!!planSources.length && (
                    <div className="next-plan-sources">
                      <strong>RAG依据</strong>
                      {planSources.map((source) => (
                        <span key={source}>{source.split(/[\\/]/).pop()}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </details>

          <p className="more-info-disclaimer">
            该结果属于知链内部岗位胜任评价，不等同于国家职业资格证书；正式上岗仍需企业、学校或有资质机构完成实操与安全复核。
          </p>
        </div>
      </aside>
    </div>
  );
}

function LearningProgressView({
  progress,
  learningPath,
  learningPathLoading,
  learningPathError,
  onNavigate,
}: {
  progress: LearningProgressResult;
  learningPath: UserLearningPath | null;
  learningPathLoading: boolean;
  learningPathError: string;
  onNavigate: (view: View) => void;
}) {
  const [detailPanel, setDetailPanel] = useState<"gates" | "dimensions" | null>(
    null,
  );
  const [expandedChapterId, setExpandedChapterId] = useState("");
  const [selectedSectionId, setSelectedSectionId] = useState("");

  const pathChapters = useMemo(
    () => learningPath?.chapters ?? [],
    [learningPath?.chapters],
  );
  const curriculumGroups = useMemo(() => {
    const groups = new Map<string, LearningPathChapter[]>();
    for (const chapter of pathChapters) {
      const groupNumber = chapter.chapter_id.split(".")[0] || "0";
      const chapters = groups.get(groupNumber) ?? [];
      chapters.push(chapter);
      groups.set(groupNumber, chapters);
    }
    return Array.from(groups.entries()).map(([groupNumber, chapters]) => ({
      id: `chapter_${groupNumber.padStart(2, "0")}`,
      number: groupNumber,
      title: `Chapter ${groupNumber} · ${chapters[0]?.chapter_id}–${chapters.at(-1)?.chapter_id}`,
      summary: `${chapters.length} 个后端课程章节`,
      chapters,
    }));
  }, [pathChapters]);

  const progressByChapterId = useMemo(
    () => new Map((learningPath?.progress ?? []).map((item) => [item.chapter_id, item])),
    [learningPath?.progress],
  );

  useEffect(() => {
    if (!detailPanel) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetailPanel(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [detailPanel]);

  const currentStageIndex = ["l1", "l2", "l3", "job_ready"].indexOf(
    progress.currentStageId,
  );
  const gateRadarItems = stageGateRadarItems(progress.gates);
  const dimensionRadarItems: RadarMetric[] = progress.dimensions.map(
    (dimension) => ({
      id: dimension.id,
      label: dimension.label,
      value: dimension.score ?? 0,
      displayValue:
        dimension.ratingStatus === "unassessed"
          ? "待评估"
          : dimension.ratingStatus === "insufficient"
            ? `暂估 ${dimension.score ?? 0}`
            : `${dimension.score ?? 0} 分`,
    }),
  );
  const passedGateCount = progress.gates.filter((gate) => gate.passed).length;
  const quickActions: Array<{
    view: Exclude<View, "progress">;
    symbol: string;
    label: string;
  }> = [
    { view: "chat", symbol: "问", label: "聊天问答" },
    { view: "quiz", symbol: "测", label: "Quiz 生成" },
    { view: "lecture", symbol: "学", label: "学习讲义" },
    { view: "memory", symbol: "人", label: "用户中心" },
  ];
  const currentPathChapter =
    pathChapters.find(
      (chapter) => chapter.chapter_id === learningPath?.current_chapter_id,
    ) ?? pathChapters[0];
  const selectedSection =
    pathChapters.find((chapter) => chapter.chapter_id === selectedSectionId) ??
    currentPathChapter;
  const activeCurriculumChapter =
    curriculumGroups.find((group) => group.id === expandedChapterId) ??
    curriculumGroups.find((group) =>
      group.chapters.some(
        (chapter) => chapter.chapter_id === selectedSection?.chapter_id,
      ),
    ) ?? curriculumGroups[0];
  const effectiveExpandedChapterId = activeCurriculumChapter?.id ?? "";
  const effectiveSelectedSectionId = selectedSection?.chapter_id ?? "";

  const sectionLearningStatus = (sectionId: string) => {
    const chapterProgress = progressByChapterId.get(sectionId);
    const status = String(chapterProgress?.status || "").toLowerCase();
    if (status === "completed" || Number(chapterProgress?.completion_rate || 0) >= 1) {
      return "completed";
    }
    if (status === "needs_review") return "review";
    if (
      ["in_progress", "learning"].includes(status) ||
      sectionId === learningPath?.current_chapter_id
    ) {
      return "current";
    }
    return "upcoming";
  };

  const selectCurriculumSection = (
    chapterId: string,
    sectionId: string,
  ) => {
    setExpandedChapterId(chapterId);
    setSelectedSectionId(sectionId);
  };

  return (
    <div className="progress-page">
      <main className="progress-surface">
        <section className="progress-dashboard" aria-label="学习进度总览">
          <div className="progress-dashboard-copy">
            <span className="eyebrow">
              {learningPathLoading
                ? "正在读取后端学习路径"
                : `当前学习路径 · ${learningPath?.path_title || progress.currentStageLabel}`}
            </span>
            <h2>
              {currentPathChapter
                ? `${currentPathChapter.chapter_id} ${currentPathChapter.chapter_title}`
                : `${progress.currentChapterId} ${progress.currentChapterTitle}`}
            </h2>
            <p>{currentPathChapter?.focus.summary || progress.currentStageOutcome}</p>
            <div className="progress-dashboard-metrics" aria-label="核心学习指标">
              <div><strong>{progress.courseCompletion}%</strong><span>课程完成</span></div>
              <div><strong>{progress.provisionalMastery}</strong><span>能力暂估</span></div>
              <div><strong>{progress.weightedConfidence}%</strong><span>评价可信度</span></div>
              <div><strong>{passedGateCount}/{progress.gates.length}</strong><span>阶段条件</span></div>
            </div>
          </div>
          <div
            className="progress-dashboard-ring"
            style={{ "--progress": `${progress.courseCompletion}%` } as React.CSSProperties}
            aria-label={`课程完成 ${progress.courseCompletion}%`}
          >
            <strong>{progress.courseCompletion}%</strong>
            <span>总体进度</span>
          </div>
        </section>

        <section className="progress-stage-strip" aria-labelledby="progress-stage-title">
          <div className="progress-stage-heading">
            <div>
              <h3 id="progress-stage-title">岗位成长阶段</h3>
              <p>阶段表示“能力到哪里”，与下方 Chapter 知识目录分开计算。</p>
            </div>
            <span>模型 {progress.modelVersion}</span>
          </div>
          <div className="progress-stage-track">
            {COURSE_PHASES.map((phase, index) => {
              const completed = index === 0 || index < currentStageIndex + 1;
              const active = phase.id === progress.currentStageId;
              return (
                <div className={`progress-stage-item ${completed ? "completed" : ""} ${active ? "active" : ""}`} key={phase.id}>
                  <span>{completed ? "✓" : index + 1}</span>
                  <div><strong>{phase.label}</strong><small>{phase.range}</small></div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="progress-curriculum" aria-labelledby="curriculum-title">
          <div className="progress-curriculum-heading">
            <div>
              <span className="eyebrow">
                {learningPath
                  ? `${learningPath.course_title} · 路径 ${learningPath.path_id}`
                  : "后端真实课程目录"}
              </span>
              <h2 id="curriculum-title">{learningPath?.path_title || "课程学习地图"}</h2>
              <p>
                {learningPath?.assignment?.classification_reason ||
                  "目录、章节顺序与学习状态均由当前用户的后端学习路径提供。"}
              </p>
            </div>
            <span className="curriculum-count">
              {learningPathLoading ? "读取中" : `${pathChapters.length} 个章节`}
            </span>
          </div>

          {learningPathLoading ? (
            <div className="progress-curriculum-state" role="status">
              正在读取后端分配路径、课程目录与章节进度…
            </div>
          ) : learningPathError || !learningPath || !pathChapters.length || !selectedSection || !activeCurriculumChapter ? (
            <div className="progress-curriculum-state error" role="alert">
              <strong>暂时无法读取后端真实学习路径</strong>
              <span>{learningPathError || "后端没有返回可用章节。"}</span>
            </div>
          ) : (
          <div className="progress-curriculum-layout">
            <div className="chapter-accordion">
              {curriculumGroups.map((chapter) => {
                const active = effectiveExpandedChapterId === chapter.id;
                const completedCount = chapter.chapters.filter(
                  (section) => sectionLearningStatus(section.chapter_id) === "completed",
                ).length;
                const hasCurrent = chapter.chapters.some(
                  (section) => ["current", "review"].includes(sectionLearningStatus(section.chapter_id)),
                );
                const chapterDone = completedCount === chapter.chapters.length;
                return (
                  <article className={`chapter-accordion-item ${hasCurrent ? "current" : ""} ${active ? "active" : ""}`} key={chapter.id}>
                    <button
                      type="button"
                      className="chapter-accordion-trigger"
                      aria-pressed={active}
                      onClick={() =>
                        selectCurriculumSection(
                          chapter.id,
                          chapter.chapters.find(
                            (section) => ["current", "review"].includes(sectionLearningStatus(section.chapter_id)),
                          )?.chapter_id ?? chapter.chapters[0].chapter_id,
                        )
                      }
                    >
                      <span className={`chapter-number ${chapterDone ? "completed" : hasCurrent ? "current" : ""}`}>
                        {chapterDone ? "✓" : chapter.number}
                      </span>
                      <span className="chapter-trigger-copy">
                        <strong>{chapter.title}</strong>
                        <small>{chapter.summary}</small>
                      </span>
                      <span className="chapter-progress-label">
                        {completedCount}/{chapter.chapters.length}
                        <i>›</i>
                      </span>
                    </button>
                  </article>
                );
              })}
            </div>

            <div className="chapter-section-browser" aria-label={`${activeCurriculumChapter.title}小节`}>
              <header>
                <span>后端目录分组</span>
                <strong>{activeCurriculumChapter.title}</strong>
                <small>{activeCurriculumChapter.chapters.length} 个章节</small>
              </header>
              <div className="chapter-section-list">
                {activeCurriculumChapter.chapters.map((section) => {
                  const status = sectionLearningStatus(section.chapter_id);
                  const selected = section.chapter_id === effectiveSelectedSectionId;
                  return (
                    <button
                      type="button"
                      className={`chapter-section-row ${status} ${selected ? "selected" : ""}`}
                      key={section.chapter_id}
                      onClick={() => selectCurriculumSection(activeCurriculumChapter.id, section.chapter_id)}
                    >
                      <span className="section-status-dot">{status === "completed" ? "✓" : ""}</span>
                      <span>
                        <strong>{section.chapter_id} {section.chapter_title}</strong>
                        <small>{section.focus.summary}</small>
                      </span>
                      <em>
                        {status === "completed"
                          ? "已完成"
                          : status === "review"
                            ? "需要复习"
                            : status === "current"
                              ? "学习中"
                              : "未开始"}
                      </em>
                    </button>
                  );
                })}
              </div>
            </div>

            <aside className="progress-next-panel" aria-label="当前小节与下一步操作">
              <span className="eyebrow">已选择知识点</span>
              <h3>{selectedSection.chapter_id} {selectedSection.chapter_title}</h3>
              <p>{selectedSection.focus.summary}</p>
              <div className="selected-section-context">
                <span>顺序 {selectedSection.chapter_order}</span>
                <span className={sectionLearningStatus(selectedSection.chapter_id)}>
                  {sectionLearningStatus(selectedSection.chapter_id) === "completed"
                    ? "已完成"
                    : sectionLearningStatus(selectedSection.chapter_id) === "review"
                      ? "需要复习"
                      : sectionLearningStatus(selectedSection.chapter_id) === "current"
                        ? "当前学习"
                        : "待学习"}
                </span>
              </div>
              <div className="selected-section-materials" aria-label="必需学习材料">
                {selectedSection.required_material_types.map((materialType) => (
                  <span key={materialType}>{learningMaterialLabel(materialType)}</span>
                ))}
              </div>
              {selectedSection.next_chapter_id && (
                <small className="selected-section-next">
                  下一章节：{selectedSection.next_chapter_id}
                </small>
              )}
              <div className="progress-next-actions">
                {quickActions.map((action) => (
                  <button type="button" key={action.view} onClick={() => onNavigate(action.view)}>
                    <span>{action.symbol}</span>
                    <strong>{action.label}</strong>
                    <small>打开</small>
                  </button>
                ))}
              </div>
              <small className="progress-next-note">这些入口仅负责页面跳转；现有接口、生成与保存逻辑保持不变。</small>
            </aside>
          </div>
          )}
        </section>

        <details className="progress-assessment-disclosure">
          <summary>
            <span><strong>岗位能力评估</strong><small>达标条件与八维能力为辅助判断，不占用主要学习视线。</small></span>
            <span>{progress.provisionalMastery} 分 · {passedGateCount}/{progress.gates.length} 项达标</span>
          </summary>
          <section className="progress-assessment" aria-labelledby="progress-assessment-title">
            <div className="progress-assessment-heading">
              <div><h2 id="progress-assessment-title">岗位胜任评价</h2><p>评分由真实学习证据自动更新，低样本不会被判定为熟练。</p></div>
              <span className="assessment-status">可信度 {progress.weightedConfidence}%</span>
            </div>
            <div className="progress-radar-grid">
              <section className="progress-gates-card radar-visual-card">
                <div className="section-heading"><div><h3>{progress.currentStageLabel} 达标条件</h3><p>安全和实操属于硬门槛，不能由其他高分抵消。</p></div></div>
                <div className="radar-card-body">
                  <OctagonRadar items={gateRadarItems} centerValue={`${passedGateCount}/${progress.gates.length}`} centerLabel="条件已达标" ariaLabel={`${progress.currentStageLabel}达标条件八边形图`} tone="gate" />
                  <button type="button" className="radar-detail-button" onClick={() => setDetailPanel("gates")}>查看详细分数</button>
                </div>
              </section>
              <section className="dimension-readiness-card radar-visual-card">
                <div className="section-heading"><div><h3>八维岗位能力</h3><p>观察表现、保守能力估计和评价可信度分别展示。</p></div></div>
                <div className="radar-card-body">
                  <OctagonRadar items={dimensionRadarItems} centerValue={`${progress.provisionalMastery}`} centerLabel="综合能力暂估" ariaLabel="八维岗位能力分数八边形图" tone="capability" />
                  <button type="button" className="radar-detail-button" onClick={() => setDetailPanel("dimensions")}>查看详细分数</button>
                </div>
              </section>
            </div>
          </section>
        </details>

      <p className="progress-method-note">
        说明：岗位能力采用固定权重、贝叶斯小样本收缩、独立尝试去重和来源审核。Quiz 只能形成知识证据；操作、质量与维护能力还必须有已复核的实操证据。本模型不等同于国家职业资格证书。
      </p>
      </main>

      {detailPanel && (
        <div
          className="score-detail-backdrop"
          role="presentation"
          onMouseDown={() => setDetailPanel(null)}
        >
          <section
            className="score-detail-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="score-detail-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="score-detail-header">
              <div>
                <h2 id="score-detail-title">
                  {detailPanel === "gates"
                    ? `${progress.currentStageLabel} 达标条件明细`
                    : "八维岗位能力分数明细"}
                </h2>
                <p>
                  {detailPanel === "gates"
                    ? "显示每项当前值、目标值和是否达标。"
                    : "显示能力暂估、观察表现、证据数量、可信度及知识/实操分数。"}
                </p>
              </div>
              <button
                type="button"
                className="score-detail-close"
                aria-label="关闭详细分数"
                onClick={() => setDetailPanel(null)}
              >
                ×
              </button>
            </header>

            {detailPanel === "gates" ? (
              <div className="progress-gates score-detail-content">
                {progress.gates.map((gate) => (
                  <div
                    className={`progress-gate ${gate.passed ? "passed" : "pending"}`}
                    key={gate.id}
                  >
                    <span className="gate-state">{gate.passed ? "✓" : "!"}</span>
                    <div>
                      <strong>{gate.label}</strong>
                      <p>当前 {gate.current} · 要求 {gate.requirement}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="dimension-progress-list score-detail-content">
                {progress.dimensions.map((dimension) => {
                  const scoreText =
                    dimension.ratingStatus === "unassessed"
                      ? "待评估"
                      : dimension.ratingStatus === "insufficient"
                        ? `暂估 ${dimension.score ?? 0} 分`
                        : `${dimension.score ?? 0} 分`;
                  const channelText = (score: number | null, status: string) =>
                    status === "unassessed"
                      ? "待评估"
                      : status === "insufficient"
                        ? `暂估 ${score ?? 0}`
                        : `${score ?? 0}`;
                  return (
                    <div
                      className={`dimension-progress ${dimension.ratingStatus}`}
                      key={dimension.id}
                    >
                      <div>
                        <strong>{dimension.label}</strong>
                        <span>{scoreText} · 权重 {dimension.weight}%</span>
                      </div>
                      <div className="dimension-track">
                        <span style={{ width: `${dimension.score ?? 0}%` }} />
                      </div>
                      <small>
                        观察表现 {dimension.observedScore === null ? "—" : `${dimension.observedScore} 分`} ·
                        有效证据 {dimension.effectiveEvidenceCount} 条 · 可信度 {dimension.confidence}%
                      </small>
                      <div className="dimension-channel-list">
                        <span>知识 {channelText(dimension.knowledgeScore, dimension.knowledgeStatus)}</span>
                        <span>实操 {channelText(dimension.practiceScore, dimension.practiceStatus)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export function LegacyMemoryView({
  profile,
  assessment,
  progress,
  setProfile,
  events,
  busy,
  onReload,
  onSaved,
}: {
  profile: LearnerProfile;
  assessment: CapabilityAssessment;
  progress: LearningProgressResult;
  setProfile: React.Dispatch<React.SetStateAction<LearnerProfile>>;
  events: MemoryEvent[];
  busy: boolean;
  onReload: () => void | Promise<void>;
  onSaved: () => void | Promise<void>;
}) {
  const capabilityResults = capabilityResultList(assessment, profile.level);
  const [detailOpen, setDetailOpen] = useState(false);
  const [logPanelCollapsed, setLogPanelCollapsed] = useState(false);
  const [logPanelPeek, setLogPanelPeek] = useState(false);
  const [logPreferenceReady, setLogPreferenceReady] = useState(false);
  const dimensionRadarItems: RadarMetric[] = capabilityResults.map((result) => ({
    id: result.id,
    label: result.label,
    value: result.score ?? 0,
    displayValue:
      result.score === null
        ? "待评估"
        : result.ratingStatus === "rated"
          ? `${result.score} 分`
          : `暂估 ${result.score}`,
  }));

  useEffect(() => {
    try {
      // Restoring a device-local layout preference requires one client-only update.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLogPanelCollapsed(
        window.localStorage.getItem(MEMORY_LOG_PANEL_PREFERENCE_KEY) === "true",
      );
    } catch {
      // Keep the update log visible when local preferences are unavailable.
    } finally {
      setLogPreferenceReady(true);
    }
  }, []);

  useEffect(() => {
    if (!logPreferenceReady) return;
    try {
      window.localStorage.setItem(
        MEMORY_LOG_PANEL_PREFERENCE_KEY,
        String(logPanelCollapsed),
      );
    } catch {
      // This local layout preference must never block Memory.
    }
  }, [logPanelCollapsed, logPreferenceReady]);

  useEffect(() => {
    if (!detailOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetailOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [detailOpen]);

  return (
    <div className="section-scroll memory-section">
      <div className="section-container memory-section-container">
        <div className="section-intro">
          <div>
            <h2>学习者 Memory</h2>
            <p>
              Memory 由结构化画像、逐题评估证据和更新记录组成。能力分数只由
              Quiz 或后续实训的客观结果计算，不能手动修改。
            </p>
          </div>
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={() => void onReload()}
          >
            {busy ? "同步中…" : "从后端刷新"}
          </button>
        </div>
        <div className={`memory-workspace ${logPanelCollapsed ? "log-panel-collapsed" : ""}`}>
          <main className="memory-main-panel">
            <section className="profile-card memory-profile-section">
              <h3 className="card-title">结构化画像</h3>
              <p className="card-subtitle">
                对应接口中的 learner_profile，修改后自动用于下一次请求。
              </p>
              <div className="profile-fields">
                <div className="form-field">
                  <label htmlFor="profile-background">学习背景</label>
                  <input
                    id="profile-background"
                    className="input"
                    value={String(profile.background)}
                    onChange={(event) =>
                      setProfile((current) => ({
                        ...current,
                        background: event.target.value,
                      }))
                    }
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="profile-level">自述水平（仅用于内容难度）</label>
                  <select
                    id="profile-level"
                    className="select"
                    value={profile.level}
                    onChange={(event) =>
                      setProfile((current) => ({
                        ...current,
                        level: event.target.value as LearnerProfile["level"],
                      }))
                    }
                  >
                    <option value="beginner">初学者</option>
                    <option value="intermediate">中级</option>
                    <option value="advanced">进阶</option>
                  </select>
                </div>
                <div className="form-field field-wide">
                  <label htmlFor="profile-preference">表达偏好</label>
                  <input
                    id="profile-preference"
                    className="input"
                    value={String(profile.preference)}
                    onChange={(event) =>
                      setProfile((current) => ({
                        ...current,
                        preference: event.target.value,
                      }))
                    }
                  />
                </div>
              </div>
              <div className="save-row">
                <span className="card-subtitle" style={{ margin: 0 }}>
                  本地自动缓存，点击保存后同步到后端
                </span>
                <button
                  type="button"
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void onSaved()}
                >
                  {busy ? "保存中…" : "保存到后端"}
                </button>
              </div>
            </section>
            <section className="scores-card memory-assessment-section">
              <div className="capability-card-heading">
                <div>
                  <h3 className="card-title">能力评估</h3>
                  <p className="card-subtitle">
                    八维岗位能力由客观学习证据自动计算，低样本只显示暂估。
                  </p>
                </div>
                <span className="assessment-version">
                  {assessment.modelVersion}
                </span>
              </div>
              <div className="memory-radar-summary">
                <OctagonRadar
                  items={dimensionRadarItems}
                  centerValue={`${progress.provisionalMastery}`}
                  centerLabel="综合能力暂估"
                  ariaLabel="Memory 八维岗位能力八边形图"
                  tone="capability"
                />
                <div className="memory-evidence-summary">
                  <span><strong>{assessment.effectiveEvidenceCount}</strong> 独立有效证据</span>
                  <span><strong>{assessment.ratedDimensionCount}/8</strong> 可评级维度</span>
                  <span><strong>{progress.weightedConfidence}%</strong> 评价可信度</span>
                </div>
                <button
                  type="button"
                  className="radar-detail-button"
                  onClick={() => setDetailOpen(true)}
                >
                  查看详细分数
                </button>
              </div>
              <div className="assessment-summary">
                <div>
                  <strong>{assessment.effectiveEvidenceCount}</strong>
                  <span>独立有效证据</span>
                </div>
                <div>
                  <strong>{assessment.ratedDimensionCount}/8</strong>
                  <span>可评级维度</span>
                </div>
                <div>
                  <strong>
                    {assessment.ratedDimensionCount
                      ? `${progress.weightedMastery}%`
                      : "待形成"}
                  </strong>
                  <span>已验证岗位能力</span>
                </div>
              </div>
              <p className="card-subtitle">
                一两道题即使全对，也只显示观察表现和“证据不足”，不会评为熟练。
                Quiz 只形成知识证据，操作能力必须等已审核的实操证据。
              </p>
              <div className="capability-list">
                {capabilityResults.map((result) => (
                  <article className="capability-row" key={result.id}>
                    <div className="capability-row-head">
                      <div>
                        <strong>{result.label}</strong>
                        <span>{result.description}</span>
                      </div>
                      <div className="capability-score">
                        <strong>
                          {result.score === null
                            ? "—"
                            : result.ratingStatus === "rated"
                              ? result.score
                              : `~${result.score}`}
                        </strong>
                        <span>{result.masteryLabel}</span>
                      </div>
                    </div>
                    <div
                      className={`score-track ${result.score === null ? "unassessed" : ""}`}
                      role="img"
                      aria-label={`${result.label}：${result.score === null ? "待评估" : `${result.score} 分`}`}
                    >
                      <div
                        className="score-fill"
                        style={{ width: `${result.score ?? 0}%` }}
                      />
                    </div>
                    <div className="capability-meta">
                      <span>
                        观察表现：
                        {result.observedScore === null ? "待评估" : `${result.observedScore}%`}
                      </span>
                      <span>{result.effectiveEvidenceCount} 条独立证据</span>
                      <span>{result.independentAttemptCount} 次独立测验</span>
                      <span>置信度：{result.confidenceLabel}</span>
                      <span>
                        {result.sourceCount
                          ? `${result.sourceCount} 个知识来源`
                          : "尚无 RAG 来源"}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
              <details className="score-method">
                <summary>查看评分方法</summary>
                <ol>
                  <li>观察表现是已作答题目的难度、时间和评分可信度加权得分率。</li>
                  <li>能力估计加入中性先验，避免一题全对直接变成 100 分。</li>
                  <li>同一题重复作答只保留首次独立证据；同次测验的同一知识点最多计一条。</li>
                  <li>至少 4 条独立证据、3 个知识点和 2 次测验，才能形成能力等级。</li>
                  <li>理论 Quiz 和已审核实操分开计分；低置信 AI 主观评分先进入待复核。</li>
                </ol>
              </details>
            </section>
          </main>
          {(!logPanelCollapsed || logPanelPeek) && (
            <aside
              className={`memory-log-panel ${logPanelCollapsed ? "overlay" : ""}`}
              onMouseLeave={() => {
                if (logPanelCollapsed) setLogPanelPeek(false);
              }}
            >
              <div className="memory-log-heading">
                <div>
                  <h3>Memory 更新记录</h3>
                  <p>{events.length} 条已保存的学习轨迹</p>
                </div>
                <button
                  type="button"
                  className="panel-collapse-button"
                  aria-label="隐藏 Memory 更新记录"
                  title="隐藏 Memory 更新记录"
                  onClick={() => {
                    setLogPanelCollapsed(true);
                    setLogPanelPeek(false);
                  }}
                >
                  <span className="panel-collapse-icon" aria-hidden="true" />
                </button>
              </div>
              <div className="memory-log">
                {events.slice(0, 20).map((event) => (
                  <article className="memory-event" key={event.id}>
                    <div className="memory-event-head">
                      <strong>{event.title}</strong>
                      <time>{event.time}</time>
                    </div>
                    <p>{event.detail}</p>
                  </article>
                ))}
              </div>
            </aside>
          )}
          {logPanelCollapsed && !logPanelPeek && (
            <button
              type="button"
              className="history-edge-trigger memory-log-edge-trigger"
              aria-label="显示 Memory 更新记录"
              title="显示 Memory 更新记录"
              onMouseEnter={() => setLogPanelPeek(true)}
              onFocus={() => setLogPanelPeek(true)}
              onClick={() => setLogPanelCollapsed(false)}
            >
              <span aria-hidden="true" />
            </button>
          )}
        </div>

        {detailOpen && (
          <div
            className="score-detail-backdrop"
            role="presentation"
            onMouseDown={() => setDetailOpen(false)}
          >
            <section
              className="score-detail-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="memory-score-detail-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header className="score-detail-header">
                <div>
                  <h2 id="memory-score-detail-title">八维岗位能力详细分数</h2>
                  <p>显示能力暂估、观察表现、证据数量、独立测验次数和评价可信度。</p>
                </div>
                <button
                  type="button"
                  className="score-detail-close"
                  aria-label="关闭详细分数"
                  onClick={() => setDetailOpen(false)}
                >
                  ×
                </button>
              </header>
              <div className="capability-list score-detail-content memory-score-details">
                {capabilityResults.map((result) => (
                  <article className="capability-row" key={result.id}>
                    <div className="capability-row-head">
                      <div>
                        <strong>{result.label}</strong>
                        <span>{result.description}</span>
                      </div>
                      <div className="capability-score">
                        <strong>
                          {result.score === null
                            ? "—"
                            : result.ratingStatus === "rated"
                              ? result.score
                              : `~${result.score}`}
                        </strong>
                        <span>{result.masteryLabel}</span>
                      </div>
                    </div>
                    <div className={`score-track ${result.score === null ? "unassessed" : ""}`}>
                      <div className="score-fill" style={{ width: `${result.score ?? 0}%` }} />
                    </div>
                    <div className="capability-meta">
                      <span>观察表现：{result.observedScore === null ? "待评估" : `${result.observedScore}%`}</span>
                      <span>{result.effectiveEvidenceCount} 条独立证据</span>
                      <span>{result.independentAttemptCount} 次独立测验</span>
                      <span>置信度：{result.confidenceLabel}</span>
                      <span>{result.sourceCount ? `${result.sourceCount} 个知识来源` : "尚无 RAG 来源"}</span>
                    </div>
                  </article>
                ))}
                <details className="score-method">
                  <summary>查看评分方法</summary>
                  <ol>
                    <li>观察表现按题目难度、作答时间和评分可信度加权。</li>
                    <li>能力估计加入中性先验，防止少量题目造成虚高分数。</li>
                    <li>同一题重复作答只保留首次独立证据。</li>
                    <li>至少 4 条独立证据、3 个知识点和 2 次测验后才形成能力等级。</li>
                    <li>理论证据与已审核实操证据分开计算。</li>
                  </ol>
                </details>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
