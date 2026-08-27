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
import { storageMarkdownBaseUrl } from "@/lib/storage-url";
import {
  COURSE_PHASES,
  calculateLearningProgress,
  type LearningProgressResult,
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

const ACTIVE_USER_ID = "user_001";
const ACTIVE_COURSE_ID = "cnc_lathe";
const ACTIVE_CHAPTER_ID = "1.1";
const QA_CONTEXT_VERSION = "cnc-domain-v2";

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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function readLocalWorkspaceCache(): LocalWorkspaceCache | null {
  try {
    const raw = window.localStorage.getItem("knowledge-chain-memory-v1");
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
      : ["personalized_question_output", "final_question_output"];

  return [
    finalOutput,
    ...specificKeys.map((key) => root?.[key]),
    finalMaterials?.[kind],
    nestedMaterials?.[kind],
  ]
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => !!item);
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

function connectionText(state: ConnectionState): string {
  if (state === "checking") return "正在连接中央调度器";
  if (state === "live") return "中央调度器已连接";
  if (state === "needs-key") return "后端已连接 · 模型密钥未配置";
  return "中央调度器待验证";
}

export default function LearningWorkspace() {
  const [activeView, setActiveView] = useState<View>("chat");
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
  const persistenceRevision = useRef(0);

  const capabilityAssessment = useMemo(
    () => calculateCapabilityAssessment(capabilityEvidence),
    [capabilityEvidence],
  );
  const scores = useMemo(
    () => assessmentToScoreMap(capabilityAssessment, profile.level),
    [capabilityAssessment, profile.level],
  );
  const learningProgress = useMemo(
    () =>
      calculateLearningProgress({
        assessment: capabilityAssessment,
        capabilityEvidence,
        profile,
        chatQuestionCount: messages.filter((message) => message.role === "user").length,
        memoryEventCount: memoryEvents.length,
        quizSessionCount: quizSessions.length,
        knowledgeGaps: backendKnowledgeGaps,
        courseProgress: backendCourseProgress,
      }),
    [
      backendCourseProgress,
      backendKnowledgeGaps,
      capabilityAssessment,
      capabilityEvidence,
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

  useEffect(() => {
    let cancelled = false;
    const cached = readLocalWorkspaceCache();
    Promise.all([checkBackendHealth(), loadBackendWorkspaceState(ACTIVE_USER_ID)])
      .then(([health, backendState]) => {
        if (cancelled) return;
        setConnection(health.model_configured ? "live" : "needs-key");
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
  }, [applyFrontendState]);

  useEffect(() => {
    if (!hydrated) return;
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
        "knowledge-chain-memory-v1",
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
      void saveBackendWorkspaceState(ACTIVE_USER_ID, {
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
    const suggestions: PendingSuggestion[] = [];
    for (const patch of response.profile_update_suggestions?.md_patches || []) {
      suggestions.push({ id: uid("profile"), kind: "profile", patch });
    }
    // Agent score patches are deliberately ignored. Ability scores are
    // derived only from graded question/practice evidence.
    if (suggestions.length) {
      setPendingSuggestions((current) => [...suggestions, ...current].slice(0, 8));
    }
  }

  async function runAgent(request: AgentRequest): Promise<AgentResponse> {
    setBusy(true);
    setTrace(PENDING_TRACE);
    setConnection("checking");
    try {
      const response = await dispatchToCentralOrchestrator({
        ...request,
        learning_progress: learningProgress.agentContext,
      });
      setConnection("live");
      setTrace(response.agent_trace || []);
      setLastResponse(response);
      addSuggestions(response);
      return response;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "无法连接中央调度器";
      setConnection(message.includes("DEEPSEEK_API_KEY") ? "needs-key" : "idle");
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
    setMemoryBusy(true);
    try {
      const backendState = await loadBackendWorkspaceState(ACTIVE_USER_ID);
      const merged = mergeBackendProfile(backendState, profile, scores);
      setProfile(merged.profile);
      setBackendKnowledgeGaps(backendState.knowledge_gaps ?? []);
      setBackendCourseProgress(backendState.learning_progress ?? []);
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

  async function saveMemory() {
    setMemoryBusy(true);
    try {
      const backendProfile = await saveBackendProfile(
        ACTIVE_USER_ID,
        profile,
        scores,
      );
      const merged = mergeBackendProfile(backendProfile, profile, scores);
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
      title: "Memory",
      detail: "维护学习者画像、能力分数和 Agent 更新建议",
    },
    progress: {
      title: "学习进度",
      detail: "依据学习证据评估从行业入门到岗位胜任的成长阶段",
    },
  }[activeView];

  return (
    <div className="app-shell">
      <Sidebar
        activeView={activeView}
        setActiveView={setActiveView}
        history={history}
        connection={connection}
        userIdentity={userIdentity}
        setUserIdentity={setUserIdentity}
      />
      <main className="workspace">
        <header className="topbar">
          <div className="page-heading">
            <h1>{pageMeta.title}</h1>
            <p>{pageMeta.detail}</p>
          </div>
          <span className="orchestrator-badge">中央调度器 · HTTP v1</span>
        </header>
        <div className="page-content">
          {activeView === "chat" && (
            <ChatView
              messages={messages}
              setMessages={setMessages}
              setHistory={setHistory}
              busy={busy}
              profile={profile}
              scores={scores}
              memoryEvents={memoryEvents}
              runAgent={runAgent}
              trace={trace}
              response={lastResponse}
              userIdentity={userIdentity}
              qaSessionId={qaSessionId}
              setQaSessionId={setQaSessionId}
              recommendations={learningRecommendations}
            />
          )}
          {activeView === "quiz" && (
            <QuizView
              busy={busy}
              profile={profile}
              scores={scores}
              recommendations={learningRecommendations}
              runAgent={runAgent}
              sessions={quizSessions}
              activeLecture={
                lectureSessions.find(
                  (lecture) => lecture.id === activeLectureSessionId,
                ) ?? null
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
                const nextScores = assessmentToScoreMap(
                  nextAssessment,
                  profile.level,
                );
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
                const feedbackRequest = buildAgentRequest({
                  userId: ACTIVE_USER_ID,
                  courseId: ACTIVE_COURSE_ID,
                  chapterId: ACTIVE_CHAPTER_ID,
                  prompt: `Quiz 作答结果：${JSON.stringify({
                    quiz_session_id: session.id,
                    topic: session.topic,
                    difficulty: session.difficulty,
                     correct: progress.correct,
                      total: progress.total,
                      earned_points: progress.earnedPoints,
                      possible_points: progress.possiblePoints,
                      accuracy: progress.accuracy,
                    evidence: evidence.map((item) => ({
                      dimension: item.dimension,
                      knowledge_point: item.knowledgePoint,
                       correct: item.correct,
                        earned: item.earned,
                        possible: item.possible,
                        question_type: item.questionType,
                        grading_method: item.gradingMethod,
                        semantic_score: item.semanticScore,
                        key_point_score: item.keyPointScore,
                      source_refs: item.sourceRefs,
                      rag_chunk_ids: item.ragChunkIds,
                    })),
                    retrieval: session.retrieval,
                  })}`,
                  contentType: "feedback",
                  scores: nextScores,
                  profile,
                });
                try {
                  await runAgent(feedbackRequest);
                  await refreshMemory(false);
                  setToast({ text: "Quiz 结果已写入后端 Memory" });
                } catch {
                  // runAgent already exposes the actionable backend error.
                }
              }}
            />
          )}
          {activeView === "lecture" && (
            <LectureView
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
              capabilityEvidence={capabilityEvidence}
              busy={busy}
              runAgent={runAgent}
              onProgressChanged={() => refreshMemory(false)}
            />
          )}
          {activeView === "memory" && (
            <MemoryView
              profile={profile}
              assessment={capabilityAssessment}
              progress={learningProgress}
              setProfile={setProfile}
              events={memoryEvents}
              setEvents={setMemoryEvents}
              suggestions={pendingSuggestions}
              setSuggestions={setPendingSuggestions}
              busy={memoryBusy}
              onReload={() => refreshMemory()}
              onSaved={saveMemory}
            />
          )}
          {activeView === "progress" && (
            <LearningProgressView
              progress={learningProgress}
              profile={profile}
              scores={scores}
              busy={busy}
              runAgent={runAgent}
            />
          )}
        </div>
      </main>
      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.text}</div>}
    </div>
  );
}

function Sidebar({
  activeView,
  setActiveView,
  history,
  connection,
  userIdentity,
  setUserIdentity,
}: {
  activeView: View;
  setActiveView: (view: View) => void;
  history: string[];
  connection: ConnectionState;
  userIdentity: UserIdentity;
  setUserIdentity: React.Dispatch<React.SetStateAction<UserIdentity>>;
}) {
  const items: Array<{ id: View; symbol: string; label: string }> = [
    { id: "chat", symbol: "问", label: "聊天问答" },
    { id: "quiz", symbol: "测", label: "Quiz 生成" },
    { id: "lecture", symbol: "学", label: "学习讲义" },
    { id: "memory", symbol: "记", label: "Memory" },
    { id: "progress", symbol: "进", label: "学习进度" },
  ];

  return (
    <aside className="sidebar">
      <div className="brand">
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
            onClick={() => setActiveView(item.id)}
          >
            <span className="nav-symbol">{item.symbol}</span>
            <span className="nav-text">{item.label}</span>
          </button>
        ))}
      </nav>
      <section className="sidebar-section">
        <p className="sidebar-label">最近问答</p>
        <div className="history-list">
          {history.length ? (
            history.slice(0, 7).map((item, index) => (
              <button
                type="button"
                className="history-item"
                key={`${item}-${index}`}
                title={item}
                onClick={() => setActiveView("chat")}
              >
                {item}
              </button>
            ))
          ) : (
            <div className="history-item">发送问题后显示记录</div>
          )}
        </div>
      </section>
      <footer className="sidebar-footer">
        <div className="connection-card">
          <span className={`status-dot ${connection}`} />
          <span>{connectionText(connection)}</span>
        </div>
        <UserProfileControl identity={userIdentity} onChange={setUserIdentity} />
      </footer>
    </aside>
  );
}

function ChatView({
  messages,
  setMessages,
  setHistory,
  busy,
  profile,
  scores,
  memoryEvents,
  runAgent,
  trace,
  response,
  userIdentity,
  qaSessionId,
  setQaSessionId,
  recommendations,
}: {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setHistory: React.Dispatch<React.SetStateAction<string[]>>;
  busy: boolean;
  profile: LearnerProfile;
  scores: ScoreMap;
  memoryEvents: MemoryEvent[];
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  trace: AgentTrace[];
  response: AgentResponse | null;
  userIdentity: UserIdentity;
  qaSessionId: string;
  setQaSessionId: React.Dispatch<React.SetStateAction<string>>;
  recommendations: LearningRecommendations;
}) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

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
      userId: ACTIVE_USER_ID,
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

  return (
    <div className={`chat-layout ${showWelcome ? "welcome-layout" : ""}`}>
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
      {!showWelcome && (
        <AgentActivity busy={busy} trace={trace} response={response} />
      )}
    </div>
  );
}

function AgentActivity({
  busy,
  trace,
  response,
}: {
  busy: boolean;
  trace: AgentTrace[];
  response: AgentResponse | null;
}) {
  const displayed = busy ? PENDING_TRACE : trace;
  const ragEvidence = response?.rag_package?.evidence ?? [];

  return (
    <aside className="activity-panel">
      <div className="activity-header">
        <div>
          <h3>Agent 活动</h3>
          <p>{busy ? "任务执行中" : trace.length ? "最近一次执行轨迹" : "等待任务"}</p>
        </div>
        {!!response && <span className="mini-chip">v1</span>}
      </div>
      {displayed.length ? (
        <div className="trace-list">
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
        <div className="empty-activity">
          发送问题后，这里会展示中央调度器返回的 agent_trace。
        </div>
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
    </aside>
  );
}

function QuizView({
  busy,
  profile,
  scores,
  recommendations,
  runAgent,
  sessions,
  activeLecture,
  activeSessionId,
  onActiveSessionChange,
  onSessionChange,
  onQuestionSubmitted,
  onFinished,
}: {
  busy: boolean;
  profile: LearnerProfile;
  scores: ScoreMap;
  recommendations: LearningRecommendations;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  sessions: QuizSession[];
  activeLecture: LectureSession | null;
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
            userId: ACTIVE_USER_ID,
            courseId: ACTIVE_COURSE_ID,
            chapterId:
              linkToCurrentLecture && activeLecture
                ? activeLecture.chapterId
                : ACTIVE_CHAPTER_ID,
            prompt,
            contentType: "quiz",
            scores,
            profile,
          }),
        );
        const generated = asQuizQuestions(response);
        if (generated.length < batch.length) {
          throw new Error(
            `中央调度器第 ${batchIndex + 1} 批只返回 ${generated.length}/${batch.length} 道有效题目，请重新生成`,
          );
        }
        responses.push(response);
        nextQuestions.push(
          ...batch.map((slot, index) => applyBlueprintToQuestion(generated[index], slot)),
        );
        const partialResponse = mergeQuizResponses(responses, nextQuestions);
        const basePartialSession = createQuizSession({
          id: sessionId,
          courseId: ACTIVE_COURSE_ID,
          chapterId:
            linkToCurrentLecture && activeLecture
              ? activeLecture.chapterId
              : ACTIVE_CHAPTER_ID,
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
          userId: ACTIVE_USER_ID,
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
    <div className="section-scroll">
      <div className="section-container">
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
        <div className="quiz-grid">
          <form className="card config-card" onSubmit={generateQuiz}>
            <h3 className="card-title">Quiz 设置</h3>
            <p className="card-subtitle">配置会被组织成任务描述传给调度器。</p>
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
                <span>根据 Memory 推荐</span>
                <small>{recommendations.contextLabel}</small>
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
                    <span>{option.reason}</span>
                  </button>
                ))}
              </div>
            </div>
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
              <small className="field-hint">
                默认 50 题，可输入 {MIN_QUIZ_QUESTION_COUNT}～{MAX_QUIZ_QUESTION_COUNT} 题；至少 8
                题以覆盖全部能力维度。
              </small>
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
            <div className="quiz-blueprint-card">
              <div>
                <strong>本次测验蓝图</strong>
                <span>{blueprintSummary.total} 题 · {blueprintSummary.totalPoints} 分原始分</span>
              </div>
              <div className="quiz-blueprint-tags">
                {(Object.entries(blueprintSummary.byType) as Array<[QuizQuestionType, number]>).map(
                  ([type, value]) => (
                    <span key={type}>{QUIZ_TYPE_LABELS[type]} {value}</span>
                  ),
                )}
                <span>难度 3:5:2</span>
                <span>八维全覆盖</span>
              </div>
            </div>
            <div className="form-field">
              <label htmlFor="quiz-focus">考查重点</label>
              <textarea
                id="quiz-focus"
                className="input"
                value={focus}
                onChange={(event) => {
                  setFocusOverride(event.target.value);
                }}
              />
            </div>
            <button
              type="submit"
              className="primary-button"
              disabled={busy || generationRunning || !topic.trim()}
              data-testid="quiz-generate"
            >
              {generationProgress ||
                (generationRunning
                  ? "题目正在生成…"
                  : busy
                    ? "中央调度器处理中…"
                    : `生成 ${blueprintSummary.total} 题 Quiz`)}
            </button>
          </form>
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

function LectureView({
  sessions,
  activeSessionId,
  onActiveSessionChange,
  onSessionCreated,
  profile,
  scores,
  progress,
  capabilityEvidence,
  busy,
  runAgent,
  onProgressChanged,
}: {
  sessions: LectureSession[];
  activeSessionId: string;
  onActiveSessionChange: (sessionId: string) => void;
  onSessionCreated: (session: LectureSession) => void;
  profile: LearnerProfile;
  scores: ScoreMap;
  progress: LearningProgressResult;
  capabilityEvidence: CapabilityEvidence[];
  busy: boolean;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
  onProgressChanged: () => void | Promise<void>;
}) {
  const [lectureError, setLectureError] = useState("");
  const [confirmNext, setConfirmNext] = useState(false);
  const activeLecture =
    sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null;
  const mastery = useMemo(
    () =>
      activeLecture
        ? calculateLectureMastery(activeLecture, capabilityEvidence)
        : null,
    [activeLecture, capabilityEvidence],
  );
  const nextChapter = activeLecture
    ? nextCourseChapter(activeLecture.chapterId)
    : null;

  async function requestLecture(
    reason: LectureGenerationReason,
    chapterId: string,
    predecessor: LectureSession | null,
  ) {
    setLectureError("");
    const chapterTitle =
      (reason === "next_stage" ? nextCourseChapter(chapterId)?.title : null) ||
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
        userId: ACTIVE_USER_ID,
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
      reason === "next_stage" ? nextCourseChapter(chapterId) : null;
    const targetChapterId = targetChapter?.id ?? chapterId;
    let session: LectureSession;
    try {
      session = createLectureSession({
        id: uid("lecture-session"),
        courseId: ACTIVE_COURSE_ID,
        chapterId: targetChapterId,
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
          userId: ACTIVE_USER_ID,
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
    try {
      await requestLecture(reason, chapterId, predecessor);
    } catch (error) {
      setLectureError(
        error instanceof Error ? error.message : "学习讲义生成失败，请检查中央调度器",
      );
    }
  }

  function requestNextStage() {
    if (!activeLecture || !nextChapter || busy) return;
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
          <span>{sessions.length}</span>
        </div>
        <div className="lecture-history-list">
          {sessions.length ? (
            sessions.map((lecture) => {
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
        </div>
      </aside>

      <section className="lecture-reader card">
        {!activeLecture ? (
          <div className="lecture-empty">
            <span>学</span>
            <h2>从当前阶段开始学习</h2>
            <p>
              知链将依据你的 Memory、岗位学习进度和 RAG 知识库，生成章节
              {progress.currentChapterId}「{progress.currentChapterTitle}」讲义。
            </p>
            <button
              type="button"
              className="primary-button"
              disabled={busy}
              onClick={() =>
                void generate("initial", progress.currentChapterId, null)
              }
            >
              {busy ? "中央调度器生成中…" : "生成当前阶段讲义"}
            </button>
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
                  disabled={busy}
                  onClick={() =>
                    void generate(
                      "regenerate",
                      activeLecture.chapterId,
                      activeLecture,
                    )
                  }
                >
                  重新生成
                </button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={busy || !nextChapter}
                  onClick={requestNextStage}
                >
                  {nextChapter ? "生成下阶段讲义" : "已是最后阶段"}
                </button>
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
                    <MarkdownContent
                      baseUrl={
                        activeLecture.artifactPath
                          ? storageMarkdownBaseUrl(activeLecture.artifactPath)
                          : undefined
                      }
                      content={section.content}
                    />
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

function LearningProgressView({
  progress,
  profile,
  scores,
  busy,
  runAgent,
}: {
  progress: LearningProgressResult;
  profile: LearnerProfile;
  scores: ScoreMap;
  busy: boolean;
  runAgent: (request: AgentRequest) => Promise<AgentResponse>;
}) {
  const [nextPlan, setNextPlan] = useState("");
  const [planSources, setPlanSources] = useState<string[]>([]);
  const [planError, setPlanError] = useState("");

  async function generateNextPlan() {
    setPlanError("");
    const prompt = [
      `请根据当前学习进度，为学习者生成一个可立即执行的下一步训练任务。`,
      `当前阶段：${progress.currentStageLabel}。`,
      `当前章节：${progress.currentChapterId} ${progress.currentChapterTitle}。`,
      `主要阻塞项：${progress.blockers.join("；") || "暂无"}。`,
      "请从已接入的数控知识库检索依据，给出学习目标、训练步骤、完成标准和安全提醒；不要虚构实操考核结果。",
    ].join("\n");
    try {
      const response = await runAgent(
        buildAgentRequest({
          userId: ACTIVE_USER_ID,
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
      setPlanError(error instanceof Error ? error.message : "下一步训练方案生成失败");
    }
  }

  const currentStageIndex = ["l1", "l2", "l3", "job_ready"].indexOf(
    progress.currentStageId,
  );

  return (
    <div className="progress-page">
      <section className="progress-hero card">
        <div className="progress-ring" style={{ "--progress": `${progress.overallProgress}%` } as React.CSSProperties}>
          <span>{progress.overallProgress}%</span>
          <small>达标条件完成度</small>
        </div>
        <div className="progress-hero-copy">
          <span className="eyebrow">当前目标 · {progress.currentStageLabel}</span>
          <h2>{progress.currentStageOutcome}</h2>
          <p>
            当前章节 {progress.currentChapterId}「{progress.currentChapterTitle}」。评价由客观学习证据自动计算，
            用户画像只用于调整学习路径，不会直接增加能力分数。
          </p>
          <div className="progress-summary-chips">
            <span>
              已验证能力贡献 {progress.verifiedWeight ? `${progress.weightedMastery} 分` : "待形成"}
            </span>
            <span>能力暂估 {progress.provisionalMastery} 分</span>
            <span>评价可信度 {progress.weightedConfidence}%</span>
            <span>课程完成 {progress.courseCompletion}%</span>
          </div>
        </div>
      </section>

      <section className="career-path card" aria-label="岗位成长路径">
        <div className="section-heading">
          <div>
            <h3>从入门到岗位胜任</h3>
            <p>课程目录与 L1/L2/L3 岗位能力门槛共同决定进度。</p>
          </div>
          <span className="model-chip">模型 {progress.modelVersion}</span>
        </div>
        <div className="career-path-steps">
          {COURSE_PHASES.map((phase, index) => {
            const completed = index === 0 || index < currentStageIndex + 1;
            const active = phase.id === progress.currentStageId;
            return (
              <article
                className={`career-step ${completed ? "completed" : ""} ${active ? "active" : ""}`}
                key={phase.id}
              >
                <span className="career-step-index">{completed ? "✓" : index + 1}</span>
                <div>
                  <strong>{phase.label}</strong>
                  <small>{phase.range}</small>
                  <p>{phase.outcome}</p>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <div className="progress-grid">
        <section className="card progress-gates-card">
          <div className="section-heading">
            <div>
              <h3>{progress.currentStageLabel} 达标条件</h3>
              <p>安全和实操属于硬门槛，不能由其他高分抵消。</p>
            </div>
          </div>
          <div className="progress-gates">
            {progress.gates.map((gate) => (
              <div className={`progress-gate ${gate.passed ? "passed" : "pending"}`} key={gate.id}>
                <span className="gate-state">{gate.passed ? "✓" : "!"}</span>
                <div>
                  <strong>{gate.label}</strong>
                  <p>当前 {gate.current} · 要求 {gate.requirement}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card evidence-layers-card">
          <div className="section-heading">
            <div>
            <h3>评价证据链</h3>
              <p>原始事件保留审计记录，只有有效、独立且已核验的证据参与评级。</p>
            </div>
          </div>
          <div className="evidence-layer-list">
            <article>
              <span>01</span>
              <div><strong>原始操作记录</strong><p>{progress.evidence.rawTraceCount} 条提问、测验与 Memory 操作轨迹</p></div>
            </article>
            <article>
              <span>02</span>
              <div><strong>结构化评价证据</strong><p>{progress.evidence.effectiveEvidenceCount}/{progress.evidence.structuredEvidenceCount} 条有效证据 · {progress.evidence.assessedDimensionCount}/8 个维度已有观察</p></div>
            </article>
            <article>
              <span>03</span>
              <div><strong>派生能力与岗位结论</strong><p>{progress.evidence.ratedDimensionCount}/8 个维度达到评级证据门槛 · {progress.blockers.length} 个待补条件</p></div>
            </article>
          </div>
          <div className="evidence-note">
            <strong>证据构成</strong>
            <span>Quiz {progress.evidence.quizEvidenceCount}</span>
            <span>实操 {progress.evidence.practicalEvidenceCount}</span>
            <span>外部考核 {progress.evidence.externalAssessmentCount}</span>
            <span>RAG 有依据 {progress.evidence.groundedEvidenceCount}</span>
          </div>
        </section>
      </div>

      <div className="progress-grid lower">
        <section className="card dimension-readiness-card">
          <div className="section-heading">
            <div>
              <h3>八维岗位能力</h3>
              <p>观察表现、保守能力估计和评价可信度分别展示；低样本不会被判定为熟练。</p>
            </div>
          </div>
          <div className="dimension-progress-list">
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
                <div className={`dimension-progress ${dimension.ratingStatus}`} key={dimension.id}>
                  <div>
                    <strong>{dimension.label}</strong>
                    <span>{scoreText} · 权重 {dimension.weight}%</span>
                  </div>
                  <div className="dimension-track"><span style={{ width: `${dimension.score ?? 0}%` }} /></div>
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
        </section>

        <section className="card next-training-card">
          <div className="section-heading">
            <div>
              <h3>下一步学习任务</h3>
              <p>由中央调度器结合 Memory、当前门槛和 RAG 知识库生成。</p>
            </div>
          </div>
          <div className="blocker-list">
            {(progress.blockers.length ? progress.blockers : ["当前阶段已达标，可进入下一阶段复核"]).slice(0, 4).map((blocker) => (
              <p key={blocker}><span>→</span>{blocker}</p>
            ))}
          </div>
          <button type="button" className="primary-button" disabled={busy} onClick={() => void generateNextPlan()}>
            {busy ? "中央调度器处理中…" : "生成下一步训练方案"}
          </button>
          {planError && <p className="inline-error">{planError}</p>}
          {nextPlan && (
            <div className="next-plan-result">
              <MarkdownContent content={nextPlan} />
              {!!planSources.length && (
                <div className="next-plan-sources">
                  <strong>RAG 依据</strong>
                  {planSources.map((source) => <span key={source}>{source.split(/[\\/]/).pop()}</span>)}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      <p className="progress-method-note">
        说明：岗位能力采用固定权重、贝叶斯小样本收缩、独立尝试去重和来源审核。Quiz 只能形成知识证据；操作、质量与维护能力还必须有已复核的实操证据。本模型不等同于国家职业资格证书。
      </p>
    </div>
  );
}

function MemoryView({
  profile,
  assessment,
  progress,
  setProfile,
  events,
  setEvents,
  suggestions,
  setSuggestions,
  busy,
  onReload,
  onSaved,
}: {
  profile: LearnerProfile;
  assessment: CapabilityAssessment;
  progress: LearningProgressResult;
  setProfile: React.Dispatch<React.SetStateAction<LearnerProfile>>;
  events: MemoryEvent[];
  setEvents: React.Dispatch<React.SetStateAction<MemoryEvent[]>>;
  suggestions: PendingSuggestion[];
  setSuggestions: React.Dispatch<React.SetStateAction<PendingSuggestion[]>>;
  busy: boolean;
  onReload: () => void | Promise<void>;
  onSaved: () => void | Promise<void>;
}) {
  const capabilityResults = capabilityResultList(assessment, profile.level);

  function applySuggestion(suggestion: PendingSuggestion) {
    const patch = suggestion.patch;
    if (patch.op === "remove") {
      setProfile((current) => ({ ...current, [patch.path]: "" }));
    } else {
      setProfile((current) => ({
        ...current,
        [patch.path]: String(patch.value ?? ""),
      }));
    }
    setEvents((current) => [
      {
        id: uid("memory-update"),
        title: "已应用 Agent 建议",
        detail: suggestion.patch.reason,
        time: new Date().toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
      ...current,
    ]);
    setSuggestions((current) =>
      current.filter((item) => item.id !== suggestion.id),
    );
  }

  return (
    <div className="section-scroll">
      <div className="section-container">
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
        <div className="memory-grid">
          <div className="memory-side">
            <section className="card profile-card">
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
            <section className="card scores-card">
              <div className="capability-card-heading">
                <div>
                  <h3 className="card-title">能力评估</h3>
                  <p className="card-subtitle">
                    观察正确率、保守能力估计、置信度和岗位评级分开展示。
                  </p>
                </div>
                <span className="assessment-version">
                  {assessment.modelVersion}
                </span>
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
          </div>
          <div className="memory-side">
            <section className="card memory-log-card">
              <h3 className="card-title">待确认的画像建议</h3>
              <p className="card-subtitle">
                来自 profile_update_suggestions，不会自动覆盖现有画像。
              </p>
              {suggestions.length ? (
                suggestions.slice(0, 4).map((suggestion) => (
                  <div className="suggestion-card" key={suggestion.id}>
                    <strong>
                      画像字段 · {suggestion.patch.path}
                    </strong>
                    <p>{suggestion.patch.reason}</p>
                    <div className="inline-actions">
                      <button
                        type="button"
                        onClick={() => applySuggestion(suggestion)}
                      >
                        应用建议
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setSuggestions((current) =>
                            current.filter((item) => item.id !== suggestion.id),
                          )
                        }
                      >
                        忽略
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-activity">
                  完成一次问答后，这里会显示 Agent 返回的画像更新建议；能力分数不接受主观建议。
                </div>
              )}
            </section>
            <section className="card memory-log-card">
              <h3 className="card-title">Memory 更新记录</h3>
              <p className="card-subtitle">记录已确认的学习行为和画像变更。</p>
              <div className="memory-log">
                {events.slice(0, 6).map((event) => (
                  <article className="memory-event" key={event.id}>
                    <div className="memory-event-head">
                      <strong>{event.title}</strong>
                      <time>{event.time}</time>
                    </div>
                    <p>{event.detail}</p>
                  </article>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
