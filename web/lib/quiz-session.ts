import type { AgentResponse, QuizQuestion } from "./agent-contract.ts";

export const QUIZ_SESSION_MODEL_VERSION = "zlink-quiz-session-v3";
export const MAX_PERSISTED_QUIZ_SESSIONS = 50;

export type QuizSessionStatus = "in_progress" | "completed" | "abandoned";
export type QuizSessionDifficulty = "easy" | "medium" | "hard";
export type QuizGenerationStatus = "generating" | "complete" | "failed";

export type QuizSessionQuestion = QuizQuestion & {
  id: string;
};

export type QuizExplanationMode = "concise" | "detailed";

export type QuizGradingResult = {
  earnedPoints: number;
  possiblePoints: number;
  isCorrect: boolean;
  gradingMethod: string;
  semanticSimilarity: number | null;
  keyPointCoverage: number | null;
  graderConfidence: number | null;
  feedback: string;
  matchedKeyPoints: string[];
  missedKeyPoints: string[];
  rubricVersion: string;
  factualityScore?: number | null;
  contradictions?: string[];
  safetyCriticalError?: boolean;
  rubricPointScores?: Array<{ index: number; score: number }>;
};

export type QuizSessionResponse = {
  questionId: string;
  selectedAnswer: string;
  submittedAt: string | null;
  isCorrect: boolean | null;
  earnedPoints: number | null;
  possiblePoints: number;
  gradingStatus: "draft" | "graded";
  gradingMethod: string;
  semanticSimilarity: number | null;
  keyPointCoverage: number | null;
  graderConfidence: number | null;
  feedback: string;
  matchedKeyPoints: string[];
  missedKeyPoints: string[];
  rubricVersion: string;
  factualityScore: number | null;
  contradictions: string[];
  safetyCriticalError: boolean;
  rubricPointScores: Array<{ index: number; score: number }>;
};

export type QuizRetrievalContext = {
  query: string;
  sourceRefs: string[];
  ragChunkIds: string[];
  confidence: number | null;
  knowledgeBaseVersion: string | null;
  retrievedAt: string;
};

export type QuizAssessmentLink = {
  lectureId: string;
  chapterId: string;
  objectiveIds: string[];
};

export type QuizSession = {
  modelVersion: typeof QUIZ_SESSION_MODEL_VERSION;
  id: string;
  requestId: string;
  courseId: string;
  chapterId: string;
  topic: string;
  focus: string;
  difficulty: QuizSessionDifficulty;
  status: QuizSessionStatus;
  generationStatus: QuizGenerationStatus;
  expectedQuestionCount: number;
  generationError: string;
  questions: QuizSessionQuestion[];
  responses: Record<string, QuizSessionResponse>;
  currentIndex: number;
  explanationMode: QuizExplanationMode;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  retrieval: QuizRetrievalContext;
  assessmentLink: QuizAssessmentLink | null;
};

export type QuizSessionProgress = {
  submitted: number;
  total: number;
  correct: number;
  earnedPoints: number;
  /** Points available in the questions that have actually been submitted. */
  possiblePoints: number;
  /** Total points for the whole paper, including unanswered questions. */
  paperPossiblePoints: number;
  completionRate: number;
  accuracy: number | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function cleanString(value: unknown, max = 20_000): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

function uniqueStrings(values: unknown[], max = 100): string[] {
  return [
    ...new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ].slice(0, max);
}

function difficulty(value: unknown): QuizSessionDifficulty {
  const normalized = cleanString(value, 30).toLowerCase();
  if (normalized === "hard" || normalized.includes("进阶")) return "hard";
  if (normalized === "medium" || normalized.includes("中等")) return "medium";
  return "easy";
}

function validDate(value: unknown, fallback: string): string {
  const text = cleanString(value, 80);
  return text && Number.isFinite(new Date(text).getTime()) ? text : fallback;
}

export function quizAnswerKey(question: QuizQuestion): string {
  if (quizQuestionType(question) === "true_false") {
    return normalizeTrueFalseAnswer(question);
  }
  const raw = cleanString(question.answer, 500).toUpperCase();
  if (/^[A-Z]$/.test(raw)) return raw;
  const optionIndex = question.options.findIndex(
    (option) => option === question.answer,
  );
  return optionIndex >= 0 ? String.fromCharCode(65 + optionIndex) : raw.slice(0, 1);
}

const TRUE_ANSWER_ALIASES = new Set([
  "a",
  "正确",
  "对",
  "是",
  "true",
  "yes",
  "1",
  "√",
]);
const FALSE_ANSWER_ALIASES = new Set([
  "b",
  "错误",
  "错",
  "否",
  "false",
  "no",
  "0",
  "×",
  "x",
]);

function normalizedBooleanToken(value: unknown): string {
  return cleanString(value, 500)
    .toLowerCase()
    .replace(/[\s。．，,：:；;！!？?（）()【】\[\]]/g, "");
}

export function normalizeTrueFalseAnswer(question: QuizQuestion): "A" | "B" | "" {
  const raw = normalizedBooleanToken(question.answer);
  if (TRUE_ANSWER_ALIASES.has(raw)) return "A";
  if (FALSE_ANSWER_ALIASES.has(raw)) return "B";

  const letter = cleanString(question.answer, 20).trim().toUpperCase();
  if (/^[A-Z]$/.test(letter)) {
    const option = question.options[letter.charCodeAt(0) - 65];
    const token = normalizedBooleanToken(option);
    if (TRUE_ANSWER_ALIASES.has(token)) return "A";
    if (FALSE_ANSWER_ALIASES.has(token)) return "B";
  }

  const matchingOption = question.options.find(
    (option) => normalizedBooleanToken(option) === raw,
  );
  const matchingToken = normalizedBooleanToken(matchingOption);
  if (TRUE_ANSWER_ALIASES.has(matchingToken)) return "A";
  if (FALSE_ANSWER_ALIASES.has(matchingToken)) return "B";
  return "";
}

export function normalizeTrueFalseQuestion(question: QuizQuestion): QuizQuestion {
  if (quizQuestionType(question) !== "true_false") return question;
  const answer = normalizeTrueFalseAnswer(question);
  return {
    ...question,
    options: ["正确", "错误"],
    answer,
    reference_answer: answer === "A" ? "正确" : answer === "B" ? "错误" : "",
  };
}

export function quizQuestionType(
  question: QuizQuestion,
): "single_choice" | "true_false" | "cloze" | "short_answer" {
  const value = cleanString(question.question_type, 40).toLowerCase();
  if (value === "true_false") return "true_false";
  if (value === "cloze") return "cloze";
  if (value === "short_answer") return "short_answer";
  return "single_choice";
}

export function quizQuestionPoints(question: QuizQuestion): number {
  const value = Number(question.points);
  if (Number.isFinite(value) && value > 0) return Math.min(100, value);
  const type = quizQuestionType(question);
  if (type === "single_choice" || type === "true_false") return 2;
  const difficulty = cleanString(question.difficulty, 50).toLowerCase();
  return difficulty.includes("hard") || difficulty.includes("进阶")
    ? 12
    : difficulty.includes("medium") || difficulty.includes("中等")
      ? 10
      : 7;
}

export function isSubjectiveQuizQuestion(question: QuizQuestion): boolean {
  const type = quizQuestionType(question);
  return type === "cloze" || type === "short_answer";
}

function conciseExplanation(text: string): string {
  const normalized = cleanString(text, 40_000).replace(/\s+/g, " ");
  if (!normalized) return "暂无解析。";
  const sentences = normalized.match(/.*?[。！？!?](?=\s|$|[^。！？!?])/g) ?? [];
  const summary = sentences[0]?.trim() || normalized;
  return summary.length > 140 ? `${summary.slice(0, 137)}…` : summary;
}

function answerForDisplay(question: QuizQuestion): string {
  if (quizQuestionType(question) === "true_false") {
    return normalizeTrueFalseAnswer(question) === "A" ? "正确" : "错误";
  }
  if (!isSubjectiveQuizQuestion(question)) {
    const key = quizAnswerKey(question);
    const option = question.options[key.charCodeAt(0) - 65];
    return option ? `${key}（${option}）` : key;
  }
  return cleanString(question.reference_answer || question.answer, 20_000);
}

/**
 * Returns genuinely different display content for the two explanation modes.
 * Old records that only contain `explanation` are enhanced from saved answer,
 * knowledge-point and rubric data; no new domain facts are invented.
 */
export function quizExplanationText(
  question: QuizQuestion,
  mode: QuizExplanationMode,
): string {
  const legacy = cleanString(question.explanation, 40_000);
  const explicitConcise = cleanString(question.concise_explanation, 10_000);
  const explicitDetailed = cleanString(question.detailed_explanation, 40_000);
  if (mode === "concise") {
    return conciseExplanation(explicitConcise || explicitDetailed || legacy);
  }

  const sections = [explicitDetailed || legacy || explicitConcise];
  const answer = answerForDisplay(question);
  if (answer) sections.push(`**参考答案：** ${answer}`);
  if (question.knowledge_point) {
    sections.push(`**考查要点：** ${cleanString(question.knowledge_point, 500)}`);
  }
  const rubricPoints = question.scoring_rubric?.key_points
    ?.map((item) => cleanString(item.description, 1_000))
    .filter(Boolean);
  if (rubricPoints?.length) {
    sections.push(`**评分要点：**\n${rubricPoints.map((item) => `- ${item}`).join("\n")}`);
  }
  return sections.filter(Boolean).join("\n\n") || "暂无解析。";
}

function responseGrounding(response: AgentResponse, timestamp: string) {
  const evidence = response.rag_package?.evidence ?? [];
  const citations = response.rag_package?.citations ?? [];
  const meta = asRecord(response.final_output?.meta);
  const sourceRefs = uniqueStrings([
    ...(response.final_output?.evidence_refs ?? []),
    ...evidence.map((item) => item.source_file ?? item.source_doc),
    ...citations.map((item) => item.source_file ?? item.source_doc),
  ]);
  const ragChunkIds = uniqueStrings([
    ...evidence.map((item) => item.chunk_id),
    ...citations.map((item) => item.chunk_id),
  ]);
  const rawConfidence = Number(response.rag_package?.confidence);
  return {
    query: cleanString(response.rag_package?.query, 4_000),
    sourceRefs,
    ragChunkIds,
    confidence: Number.isFinite(rawConfidence)
      ? Math.max(0, Math.min(1, rawConfidence))
      : null,
    knowledgeBaseVersion:
      cleanString(
        response.rag_package?.knowledge_base_version ??
          meta?.knowledge_base_version ??
          meta?.corpus_version,
        200,
      ) || null,
    retrievedAt: timestamp,
  } satisfies QuizRetrievalContext;
}

export function createQuizSession(input: {
  id: string;
  courseId: string;
  chapterId: string;
  topic: string;
  focus: string;
  difficulty: QuizSessionDifficulty;
  questions: QuizQuestion[];
  response: AgentResponse;
  assessmentLink?: QuizAssessmentLink | null;
  createdAt?: string;
}): QuizSession {
  const timestamp = input.createdAt || new Date().toISOString();
  const retrieval = responseGrounding(input.response, timestamp);
  const questions = input.questions.map((rawQuestion, index) => {
    const question = normalizeTrueFalseQuestion(rawQuestion);
    return {
    ...question,
    id: `${input.id}-q${index + 1}`,
    stem: cleanString(question.stem),
    options: question.options.map((option) => cleanString(option, 5_000)),
    answer: cleanString(question.answer, 5_000),
    reference_answer:
      cleanString(question.reference_answer, 20_000) ||
      cleanString(question.answer, 20_000),
    explanation: cleanString(question.explanation),
    concise_explanation:
      cleanString(question.concise_explanation, 10_000) || undefined,
    detailed_explanation:
      cleanString(question.detailed_explanation, 40_000) || undefined,
    difficulty: cleanString(question.difficulty, 50) || input.difficulty,
    question_type: quizQuestionType(question),
    points: quizQuestionPoints(question),
    scoring_rubric: question.scoring_rubric,
    capability_dimension: cleanString(question.capability_dimension, 80) || undefined,
    knowledge_point: cleanString(question.knowledge_point, 300) || undefined,
    source_refs: uniqueStrings([
      ...(question.source_refs ?? []),
      ...retrieval.sourceRefs,
    ]),
    rag_chunk_ids: uniqueStrings([
      ...(question.rag_chunk_ids ?? []),
      ...retrieval.ragChunkIds,
    ]),
    source_grounding_scope:
      question.source_refs?.length || question.rag_chunk_ids?.length
        ? "question"
        : retrieval.sourceRefs.length || retrieval.ragChunkIds.length
          ? "session"
          : "none",
    };
  });
  return {
    modelVersion: QUIZ_SESSION_MODEL_VERSION,
    id: input.id,
    requestId: input.response.request_id,
    courseId: input.courseId,
    chapterId: input.chapterId,
    topic: cleanString(input.topic, 500),
    focus: cleanString(input.focus, 2_000),
    difficulty: input.difficulty,
    status: "in_progress",
    generationStatus: "complete",
    expectedQuestionCount: questions.length,
    generationError: "",
    questions,
    responses: {},
    currentIndex: 0,
    explanationMode: "detailed",
    createdAt: timestamp,
    updatedAt: timestamp,
    completedAt: null,
    retrieval,
    assessmentLink: input.assessmentLink
      ? {
          lectureId: cleanString(input.assessmentLink.lectureId, 150),
          chapterId: cleanString(input.assessmentLink.chapterId, 150),
          objectiveIds: uniqueStrings(input.assessmentLink.objectiveIds),
        }
      : null,
  };
}

export function quizSessionProgress(session: QuizSession): QuizSessionProgress {
  const submittedResponses = session.questions
    .map((question) => session.responses[question.id])
    .filter((response) => !!response?.submittedAt);
  const correct = submittedResponses.filter(
    (response) => response.isCorrect === true,
  ).length;
  const earnedPoints = submittedResponses.reduce(
    (sum, response) => sum + Number(response.earnedPoints || 0),
    0,
  );
  const submittedPossiblePoints = submittedResponses.reduce(
    (sum, response) => sum + Number(response.possiblePoints || 0),
    0,
  );
  const paperPossiblePoints = session.questions.reduce(
    (sum, question) => sum + quizQuestionPoints(question),
    0,
  );
  return {
    submitted: submittedResponses.length,
    total: session.questions.length,
    correct,
    earnedPoints: Number(earnedPoints.toFixed(2)),
    possiblePoints: Number(submittedPossiblePoints.toFixed(2)),
    paperPossiblePoints: Number(paperPossiblePoints.toFixed(2)),
    completionRate: session.questions.length
      ? submittedResponses.length / session.questions.length
      : 0,
    accuracy: submittedResponses.length && submittedPossiblePoints
      ? earnedPoints / submittedPossiblePoints
      : null,
  };
}

export function updateQuizDraft(
  session: QuizSession,
  questionId: string,
  selectedAnswer: string,
  updatedAt = new Date().toISOString(),
): QuizSession {
  const existing = session.responses[questionId];
  if (existing?.submittedAt || !session.questions.some((item) => item.id === questionId)) {
    return session;
  }
  return {
    ...session,
    responses: {
      ...session.responses,
      [questionId]: {
        questionId,
        selectedAnswer: cleanString(selectedAnswer, 20_000),
        submittedAt: null,
        isCorrect: null,
        earnedPoints: null,
        possiblePoints: quizQuestionPoints(
          session.questions.find((item) => item.id === questionId)!,
        ),
        gradingStatus: "draft",
        gradingMethod: "",
        semanticSimilarity: null,
        keyPointCoverage: null,
        graderConfidence: null,
        feedback: "",
        matchedKeyPoints: [],
        missedKeyPoints: [],
        rubricVersion: "",
        factualityScore: null,
        contradictions: [],
        safetyCriticalError: false,
        rubricPointScores: [],
      },
    },
    updatedAt,
  };
}

export function submitQuizAnswer(
  session: QuizSession,
  questionId: string,
  gradingOrSubmittedAt?: QuizGradingResult | string,
  explicitSubmittedAt = new Date().toISOString(),
): QuizSession {
  const grading =
    typeof gradingOrSubmittedAt === "string" ? undefined : gradingOrSubmittedAt;
  const submittedAt =
    typeof gradingOrSubmittedAt === "string"
      ? gradingOrSubmittedAt
      : explicitSubmittedAt;
  const question = session.questions.find((item) => item.id === questionId);
  const existing = session.responses[questionId];
  if (!question || !existing?.selectedAnswer || existing.submittedAt) return session;
  if (isSubjectiveQuizQuestion(question) && !grading) return session;
  const answerCorrect = existing.selectedAnswer === quizAnswerKey(question);
  const possiblePoints = quizQuestionPoints(question);
  const earnedPoints = grading
    ? Math.max(0, Math.min(possiblePoints, grading.earnedPoints))
    : answerCorrect
      ? possiblePoints
      : 0;
  const nextResponses = {
    ...session.responses,
    [questionId]: {
      ...existing,
      submittedAt,
      isCorrect: grading?.isCorrect ?? answerCorrect,
      earnedPoints,
      possiblePoints,
      gradingStatus: "graded" as const,
      gradingMethod: grading?.gradingMethod || "exact_answer_key",
      semanticSimilarity: grading?.semanticSimilarity ?? null,
      keyPointCoverage: grading?.keyPointCoverage ?? null,
      graderConfidence: grading?.graderConfidence ?? 1,
      feedback: grading?.feedback || "",
      matchedKeyPoints: grading?.matchedKeyPoints ?? [],
      missedKeyPoints: grading?.missedKeyPoints ?? [],
      rubricVersion: grading?.rubricVersion || "objective-v1",
      factualityScore: grading?.factualityScore ?? null,
      contradictions: grading?.contradictions ?? [],
      safetyCriticalError: grading?.safetyCriticalError === true,
      rubricPointScores: grading?.rubricPointScores ?? [],
    },
  };
  const completed = session.questions.every(
    (item) => !!nextResponses[item.id]?.submittedAt,
  );
  return {
    ...session,
    responses: nextResponses,
    status: completed ? "completed" : "in_progress",
    completedAt: completed ? submittedAt : session.completedAt,
    updatedAt: submittedAt,
  };
}

export function setQuizExplanationMode(
  session: QuizSession,
  explanationMode: QuizExplanationMode,
  updatedAt = new Date().toISOString(),
): QuizSession {
  return { ...session, explanationMode, updatedAt };
}

export function setQuizCurrentIndex(
  session: QuizSession,
  index: number,
  updatedAt = new Date().toISOString(),
): QuizSession {
  const maximum = Math.max(0, session.questions.length - 1);
  return {
    ...session,
    currentIndex: Math.max(0, Math.min(maximum, Math.trunc(index))),
    updatedAt,
  };
}

export function upsertQuizSession(
  sessions: QuizSession[],
  session: QuizSession,
): QuizSession[] {
  return [session, ...sessions.filter((item) => item.id !== session.id)]
    .sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    )
    .slice(0, MAX_PERSISTED_QUIZ_SESSIONS);
}

function normalizeQuestion(
  value: unknown,
  sessionId: string,
  index: number,
): QuizSessionQuestion | null {
  const item = asRecord(value);
  if (!item || typeof item.stem !== "string") {
    return null;
  }
  const rawOptions = Array.isArray(item.options) ? item.options : [];
  const options = rawOptions
    .filter((option: unknown): option is string => typeof option === "string")
    .map((option) => cleanString(option, 5_000));
  const type = quizQuestionType(item as QuizQuestion);
  if ((type === "single_choice" || type === "true_false") && options.length < 2) {
    return null;
  }
  const normalized = normalizeTrueFalseQuestion({
    ...(item as QuizQuestion),
    options,
    question_type: type,
  });
  if (type === "true_false" && !normalized.answer) return null;
  return {
    id: cleanString(item.id, 150) || `${sessionId}-q${index + 1}`,
    stem: cleanString(item.stem),
    options: normalized.options,
    answer: cleanString(normalized.answer, 5_000),
    reference_answer:
      cleanString(normalized.reference_answer, 20_000) || cleanString(normalized.answer, 20_000),
    explanation: cleanString(item.explanation),
    concise_explanation: cleanString(item.concise_explanation, 10_000) || undefined,
    detailed_explanation: cleanString(item.detailed_explanation, 40_000) || undefined,
    difficulty: cleanString(item.difficulty, 50) || "easy",
    question_type: type,
    points: quizQuestionPoints(item as QuizQuestion),
    scoring_rubric: asRecord(item.scoring_rubric) as QuizQuestion["scoring_rubric"],
    capability_dimension:
      cleanString(item.capability_dimension, 80) || undefined,
    knowledge_point: cleanString(item.knowledge_point, 300) || undefined,
    source_refs: uniqueStrings(Array.isArray(item.source_refs) ? item.source_refs : []),
    rag_chunk_ids: uniqueStrings(
      Array.isArray(item.rag_chunk_ids) ? item.rag_chunk_ids : [],
    ),
    source_grounding_scope:
      item.source_grounding_scope === "question" ||
      item.source_grounding_scope === "session"
        ? item.source_grounding_scope
        : "none",
    backend_artifact_id:
      cleanString(item.backend_artifact_id, 150) || undefined,
    backend_question_id:
      cleanString(item.backend_question_id, 150) || undefined,
  };
}

export function normalizeQuizSessions(value: unknown): QuizSession[] {
  if (!Array.isArray(value)) return [];
  const now = new Date().toISOString();
  const sessions = value.flatMap((candidate) => {
    const item = asRecord(candidate);
    const id = cleanString(item?.id, 150);
    if (!item || !id || !Array.isArray(item.questions)) return [];
    const questions = item.questions
      .map((question, index) => normalizeQuestion(question, id, index))
      .filter((question): question is QuizSessionQuestion => !!question);
    if (!questions.length) return [];
    const responseRoot = asRecord(item.responses) ?? {};
    const responses = Object.fromEntries(
      questions.flatMap((question) => {
        const response = asRecord(responseRoot[question.id]);
        const selectedAnswer = cleanString(response?.selectedAnswer, 20_000);
        if (!selectedAnswer) return [];
        const submittedAt = cleanString(response?.submittedAt, 80) || null;
        return [
          [
            question.id,
            {
              questionId: question.id,
              selectedAnswer,
              submittedAt,
              isCorrect:
                submittedAt && typeof response?.isCorrect === "boolean"
                  ? response.isCorrect
                  : submittedAt
                    ? selectedAnswer === quizAnswerKey(question)
                    : null,
              earnedPoints: submittedAt
                ? Number.isFinite(Number(response?.earnedPoints))
                  ? Number(response?.earnedPoints)
                  : selectedAnswer === quizAnswerKey(question)
                    ? quizQuestionPoints(question)
                    : 0
                : null,
              possiblePoints: Number.isFinite(Number(response?.possiblePoints))
                ? Number(response?.possiblePoints)
                : quizQuestionPoints(question),
              gradingStatus: submittedAt ? "graded" : "draft",
              gradingMethod: cleanString(response?.gradingMethod, 120) ||
                (submittedAt ? "legacy_exact_answer_key" : ""),
              semanticSimilarity: Number.isFinite(Number(response?.semanticSimilarity))
                ? Number(response?.semanticSimilarity)
                : null,
              keyPointCoverage: Number.isFinite(Number(response?.keyPointCoverage))
                ? Number(response?.keyPointCoverage)
                : null,
              graderConfidence: Number.isFinite(Number(response?.graderConfidence))
                ? Number(response?.graderConfidence)
                : null,
              feedback: cleanString(response?.feedback, 20_000),
              matchedKeyPoints: uniqueStrings(
                Array.isArray(response?.matchedKeyPoints) ? response.matchedKeyPoints : [],
              ),
              missedKeyPoints: uniqueStrings(
                Array.isArray(response?.missedKeyPoints) ? response.missedKeyPoints : [],
              ),
              rubricVersion: cleanString(response?.rubricVersion, 120),
              factualityScore: Number.isFinite(Number(response?.factualityScore))
                ? Number(response?.factualityScore)
                : null,
              contradictions: uniqueStrings(
                Array.isArray(response?.contradictions) ? response.contradictions : [],
              ),
              safetyCriticalError: response?.safetyCriticalError === true,
              rubricPointScores: Array.isArray(response?.rubricPointScores)
                ? response.rubricPointScores.flatMap((value) => {
                    const point = asRecord(value);
                    const index = Number(point?.index);
                    const score = Number(point?.score);
                    return Number.isInteger(index) && Number.isFinite(score)
                      ? [{ index, score: Math.max(0, Math.min(1, score)) }]
                      : [];
                  })
                : [],
            } satisfies QuizSessionResponse,
          ],
        ];
      }),
    );
    const createdAt = validDate(item.createdAt, now);
    const updatedAt = validDate(item.updatedAt, createdAt);
    const completed = questions.every(
      (question) => !!responses[question.id]?.submittedAt,
    );
    const retrievalRoot = asRecord(item.retrieval) ?? {};
    const assessmentLinkRoot = asRecord(item.assessmentLink);
    const rawConfidence = Number(retrievalRoot.confidence);
    const session: QuizSession = {
      modelVersion: QUIZ_SESSION_MODEL_VERSION,
      id,
      requestId: cleanString(item.requestId, 200),
      courseId: cleanString(item.courseId, 200),
      chapterId: cleanString(item.chapterId, 200),
      topic: cleanString(item.topic, 500) || "未命名 Quiz",
      focus: cleanString(item.focus, 2_000),
      difficulty: difficulty(item.difficulty),
      status:
        item.status === "abandoned"
          ? "abandoned"
          : completed
            ? "completed"
            : "in_progress",
      // A browser refresh cannot resume an in-memory generation loop. Mark a
      // previously generating record as failed so the saved questions remain
      // usable and the learner is not locked out indefinitely.
      generationStatus:
        item.generationStatus === "generating"
          ? "failed"
          : item.generationStatus === "failed"
            ? "failed"
            : "complete",
      expectedQuestionCount: Math.max(
        questions.length,
        Math.trunc(Number(item.expectedQuestionCount) || questions.length),
      ),
      generationError:
        item.generationStatus === "generating"
          ? "上次题目生成在页面关闭或刷新时中断，已保留成功生成的题目。"
          : cleanString(item.generationError, 2_000),
      questions,
      responses,
      currentIndex: Math.max(
        0,
        Math.min(
          questions.length - 1,
          Math.trunc(Number(item.currentIndex) || 0),
        ),
      ),
      explanationMode: item.explanationMode === "concise" ? "concise" : "detailed",
      createdAt,
      updatedAt,
      completedAt: completed
        ? validDate(item.completedAt, updatedAt)
        : null,
      retrieval: {
        query: cleanString(retrievalRoot.query, 4_000),
        sourceRefs: uniqueStrings(
          Array.isArray(retrievalRoot.sourceRefs)
            ? retrievalRoot.sourceRefs
            : [],
        ),
        ragChunkIds: uniqueStrings(
          Array.isArray(retrievalRoot.ragChunkIds)
            ? retrievalRoot.ragChunkIds
            : [],
        ),
        confidence: Number.isFinite(rawConfidence)
          ? Math.max(0, Math.min(1, rawConfidence))
          : null,
        knowledgeBaseVersion:
          cleanString(retrievalRoot.knowledgeBaseVersion, 200) || null,
        retrievedAt: validDate(retrievalRoot.retrievedAt, createdAt),
      },
      assessmentLink:
        assessmentLinkRoot && cleanString(assessmentLinkRoot.lectureId, 150)
          ? {
              lectureId: cleanString(assessmentLinkRoot.lectureId, 150),
              chapterId: cleanString(assessmentLinkRoot.chapterId, 150),
              objectiveIds: uniqueStrings(
                Array.isArray(assessmentLinkRoot.objectiveIds)
                  ? assessmentLinkRoot.objectiveIds
                  : [],
              ),
            }
          : null,
    };
    return [session];
  });
  return sessions
    .sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    )
    .slice(0, MAX_PERSISTED_QUIZ_SESSIONS);
}
