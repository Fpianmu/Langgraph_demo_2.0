import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { buildLearningRecommendations } from "../lib/learning-recommendations.ts";
import {
  assessmentToScoreMap,
  calculateCapabilityAssessment,
  createQuizEvidence,
} from "../lib/capability-assessment.ts";
import {
  createQuizSession,
  normalizeTrueFalseQuestion,
  normalizeQuizSessions,
  quizExplanationText,
  quizSessionProgress,
  submitQuizAnswer,
  updateQuizDraft,
} from "../lib/quiz-session.ts";
import {
  createQuizBlueprint,
  summarizeQuizBlueprint,
} from "../lib/quiz-blueprint.ts";
import {
  calculateLearningProgress,
  LEARNING_PROGRESS_MODEL_VERSION,
} from "../lib/learning-progress.ts";
import { normalizeCapabilityScoresPayload } from "../lib/capability-score-client.ts";
import { normalizeKnowledgeGapPayload } from "../lib/knowledge-gap-client.ts";
import { normalizeResourceDifficultyTrace } from "../lib/resource-difficulty-client.ts";
import {
  calculateLectureMastery,
  createLectureSession,
  normalizeLectureSessions,
} from "../lib/lecture-session.ts";

async function loadWorker() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker;
}

const environment = {
  ASSETS: {
    fetch: async () => new Response("Not found", { status: 404 }),
  },
};

const context = {
  waitUntil() {},
  passThroughOnException() {},
};

test("uses backend profile-score as the authoritative eight-dimension source", () => {
  const normalized = normalizeCapabilityScoresPayload({
    user_id: "user_001",
    scores: { safety: 99, overall: 99 },
    capability_profile_score: {
      overall: 54.67,
      dimensions: {
        safety: 55,
        programming: 54,
        machining_operation: 55,
      },
      source: "capability_assessment.score_map",
    },
    capability_assessment: {
      assessment: {
        dimensions: {
          safety: {
            score: 99,
            confidence: 0.42,
            evidenceCount: 3,
            ratingReady: true,
            masteryLabel: "基本掌握",
          },
        },
      },
    },
  });

  assert.equal(normalized.profileScore.overall, 54.67);
  assert.equal(normalized.scores.overall, 54.67);
  assert.equal(normalized.assessment.dimensions.safety.score, 55);
  assert.equal(normalized.assessment.dimensions.safety.confidence, 0.42);
  assert.equal(normalized.assessment.dimensions.safety.evidenceCount, 3);
  assert.equal(normalized.assessment.dimensions.safety.ratingReady, true);
  assert.equal(normalized.assessment.dimensions.safety.masteryLabel, "基本掌握");
  assert.equal(normalized.assessment.dimensions.programming.score, 54);
  assert.equal(normalized.assessment.dimensions.machining_operation.score, 55);
  assert.equal(normalized.assessment.dimensions.foundations.score, 0);
  assert.equal(normalized.assessment.dimensions.process_planning.score, 0);
  assert.equal(normalized.assessment.dimensions.quality_control.score, 0);
  assert.equal(normalized.assessment.dimensions.maintenance.score, 0);
  assert.equal(normalized.assessment.dimensions.advanced_manufacturing.score, 0);
  assert.equal(Object.keys(normalized.assessment.dimensions).length, 8);
});

test("normalizes the dedicated knowledge-gap payload and JSON action fields", () => {
  const normalized = normalizeKnowledgeGapPayload({
    user_id: "user_001",
    knowledge_gaps: [
      {
        gap_id: "gap-1",
        knowledge_point_id: "3.5",
        concept: "刀补设置",
        chapter_id: "3.5",
        category: "programming",
        severity: "high",
        score: 0.42,
        status: "open",
        evidence: "连续两次回答错误",
        evidence_items_json: '[{"type":"quiz","summary":"题目 7 错误"}]',
        recommended_actions_json: '["复习刀补建立与取消"]',
      },
    ],
    knowledge_gap_summary: {
      open_count: 1,
      high_count: 1,
      medium_count: 0,
      low_count: 0,
      resolved_count: 2,
    },
  });

  assert.equal(normalized.userId, "user_001");
  assert.equal(normalized.summary.resolvedCount, 2);
  assert.equal(normalized.knowledgeGaps[0].score, 42);
  assert.equal(normalized.knowledgeGaps[0].recommendedActions[0], "复习刀补建立与取消");
  assert.equal(normalized.knowledgeGaps[0].evidenceItems[0].summary, "题目 7 错误");
});

test("normalizes difficulty trace records from the dedicated storage API", () => {
  const normalized = normalizeResourceDifficultyTrace({
    user_id: "user_001",
    capability_profile_score: { overall: 55, dimensions: { programming: 54 } },
    resource_difficulty_records: [
      {
        record_id: "difficulty-1",
        resource_id: "lecture-3.5",
        resource_type: "lecture",
        chapter_id: "3.5",
        profile_score: 55,
        resource_difficulty: 62,
        difficulty_delta: 7,
        alignment_score: 93,
        resource_meta_json: '{"title":"刀补设置讲义"}',
      },
    ],
  });

  assert.equal(normalized.capability_profile_score.overall, 55);
  assert.equal(normalized.resource_difficulty_records[0].alignment_score, 93);
  assert.equal(normalized.resource_difficulty_records[0].resource_meta.title, "刀补设置讲义");
});

test("server-renders the finished learning workspace", async () => {
  const worker = await loadWorker();
  const response = await worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    environment,
    context,
  );

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>知链<\/title>/);
  assert.match(html, /聊天问答/);
  assert.match(html, /Quiz 生成/);
  assert.match(html, /学习讲义/);
  assert.match(html, /Memory/);
  assert.match(html, /学习进度/);
  assert.match(html, /中央调度器/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("rejects requests that do not match the v2 agent contract", async () => {
  const worker = await loadWorker();
  const response = await worker.fetch(
    new Request("http://localhost/api/agent", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    }),
    environment,
    context,
  );

  assert.equal(response.status, 400);
  const body = await response.json();
  assert.equal(body.code, "INVALID_REQUEST");
});

test("keeps the central orchestrator and Memory contracts explicit", async () => {
  const [contract, client, route, profileRoute, profileClient, workspace] = await Promise.all([
    readFile(new URL("../lib/agent-contract.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/orchestrator-client.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/agent/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/profile/[userId]/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/profile-client.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/LearningWorkspace.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(contract, /content_type:\s*ContentType/);
  assert.match(contract, /latest_scores:\s*ScoreMap/);
  assert.match(contract, /learner_profile:\s*LearnerProfile/);
  assert.match(client, /dispatchToCentralOrchestrator/);
  assert.match(route, /api\/graph\/runs/);
  assert.match(client, /new EventSource/);
  assert.match(client, /run\.completed/);
  assert.match(contract, /qa_session_id\?:\s*string/);
  assert.match(profileRoute, /api\/frontend-state/);
  assert.match(profileClient, /saveBackendProfile/);
  assert.doesNotMatch(client, /createDemoResponse|demoQuestions/);
  assert.match(workspace, /本次请求未生成任何本地演示内容/);
  assert.match(workspace, /生成后会立即保存，刷新页面也能继续作答/);
  assert.match(workspace, /Quiz 作答、能力证据和知识漏洞已写入后端/);
  assert.match(workspace, /personalized_qa_output/);
  assert.match(workspace, /nestedMaterials/);
});

test("renders assistant answers as safe structured Markdown", async () => {
  const [workspace, markdown, styles] = await Promise.all([
    readFile(new URL("../components/LearningWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/MarkdownContent.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(workspace, /message\.role === "assistant"/);
  assert.match(workspace, /<MarkdownContent content=\{message\.content\}/);
  assert.match(markdown, /ReactMarkdown/);
  assert.match(markdown, /remarkGfm/);
  assert.match(markdown, /skipHtml/);
  assert.doesNotMatch(markdown, /dangerouslySetInnerHTML|rehypeRaw/);
  assert.match(styles, /\.markdown-content h2/);
  assert.match(styles, /\.markdown-content strong/);
  assert.match(styles, /\.markdown-content (ul|ol)/);
  assert.match(styles, /\.markdown-table-wrap/);
});

test("grounds vague questions in the CNC course and forwards Memory context", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, state, inputRouter, generators, personalization, domainContext, courseManifest] =
    await Promise.all([
      readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
      readFile(
        new URL(
          "../agent/state.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/node/task_dispatch/input_router.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/node/knowledge_generation/generators.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/node/personalized_generation/personalization_node.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/course_resources/repository.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/course_resources/cnc_lathe/course_manifest.json",
          projectRoot,
        ),
        "utf8",
      ),
    ]);

  assert.match(workspace, /const ACTIVE_CHAPTER_ID = "1\.1"/);
  assert.match(workspace, /const QA_CONTEXT_VERSION = "cnc-domain-v2"/);
  assert.match(workspace, /snapshot\.qa_context_version === QA_CONTEXT_VERSION/);
  assert.match(workspace, /knowledge_domain/);
  assert.match(workspace, /active_learning_topic: recommendations\.primaryTopic/);
  assert.match(workspace, /recent_memory: memoryEvents/);
  assert.match(state, /learner_profile: dict\[str, Any\]/);
  assert.match(state, /latest_scores: dict\[str, float\]/);
  assert.match(inputRouter, /raw_prompt/);
  assert.match(inputRouter, /rag_questions/);
  assert.match(generators, /load_qa_session_context/);
  assert.match(personalization, /load_profile_context/);
  assert.match(personalization, /course_resource_bundle/);
  assert.match(courseManifest, /cnc_lathe/);
  assert.match(domainContext, /load_chapter_asset_bundle/);
});

test("persists and restores the complete ZLink workspace state", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, stateClient, stateRoute, server, repository, storageLayout] =
    await Promise.all([
      readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
      readFile(new URL("lib/workspace-state-client.ts", projectRoot), "utf8"),
      readFile(new URL("app/api/state/[userId]/route.ts", projectRoot), "utf8"),
      readFile(
        new URL(
          "../agent/api.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/frontend_state.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/storage_layout.py",
          projectRoot,
        ),
        "utf8",
      ),
    ]);

  assert.match(workspace, /loadBackendWorkspaceState/);
  assert.match(workspace, /saveBackendWorkspaceState/);
  assert.match(workspace, /messages: messages\.slice/);
  assert.match(workspace, /memory_events: memoryEvents\.slice/);
  assert.match(stateClient, /frontend_state: FrontendStateSnapshot/);
  assert.match(stateRoute, /api\/frontend-state/);
  assert.match(server, /@app\.get\("\/api\/frontend-state\/\{user_id\}"\)/);
  assert.match(server, /@app\.put\("\/api\/frontend-state\/\{user_id\}"\)/);
  assert.match(repository, /workspace_state\.json/);
  assert.match(repository, /incoming_revision < current_revision/);
  assert.match(storageLayout, /web" \/ "runtime" \/ DOC_DIR/);
});

test("uses CNC-domain recommendations before RAG is connected", () => {
  const result = buildLearningRecommendations({
    profile: {
      background: "非机械专业",
      level: "beginner",
      preference: "步骤化、少术语",
    },
    scores: { theory: 70, safety: 58, operation: 65 },
  });

  assert.equal(result.primaryTopic, "数控机床安全操作");
  assert.equal(result.chatPrompts.length, 4);
  assert.match(result.chatPrompts.join("\n"), /数控|车铣|多轴/);
  assert.doesNotMatch(result.chatPrompts.join("\n"), /多 Agent|RAG|中央调度器/);
});

test("changes recommendations when Memory changes", () => {
  const base = {
    profile: {
      background: "机械专业",
      level: "intermediate",
      preference: "结合案例",
    },
    scores: { theory: 70, safety: 70, operation: 70 },
  };
  const before = buildLearningRecommendations(base);
  const after = buildLearningRecommendations({
    ...base,
    memoryEvents: [
      {
        title: "近期复习目标",
        detail: "准备高级职业技能等级证书考核",
      },
    ],
  });

  assert.notEqual(after.primaryTopic, before.primaryTopic);
  assert.equal(after.primaryTopic, "数控车铣加工职业技能等级考核");
  assert.equal(after.origin, "memory");
});

test("prefers grounded document topics when RAG evidence becomes available", () => {
  const result = buildLearningRecommendations({
    profile: {
      background: "机械专业",
      level: "intermediate",
      preference: "结合案例",
    },
    scores: { theory: 70, safety: 70, operation: 70 },
    ragPackage: {
      evidence: [
        {
          source_doc: "数控车铣加工职业技能等级考核（初级）考核大纲.docx",
          text: "安全操作和规范要求",
          score: 0.92,
        },
      ],
    },
  });

  assert.equal(result.origin, "rag");
  assert.match(result.quizOptions[0].topic, /初级.*考核大纲/);
  assert.match(result.chatPrompts[0], /结合《.*考核大纲》/);
});

test("calculates read-only capability scores from graded quiz evidence", () => {
  const occurredAt = "2026-08-18T08:00:00.000Z";
  const evidence = [true, true, true, false].map((correct, index) => ({
    id: `attempt-1-q${index + 1}`,
    attemptId: "attempt-1",
    sourceType: "quiz",
    dimension: "programming",
    topic: "数控编程",
    knowledgePoint: `G 代码 ${index + 1}`,
    correct,
    earned: correct ? 1 : 0,
    possible: 1,
    difficulty: "easy",
    occurredAt,
    sourceRefs: [],
    ragChunkIds: [],
  }));
  const assessment = calculateCapabilityAssessment(
    evidence,
    new Date(occurredAt),
  );

  assert.equal(assessment.dimensions.programming.observedScore, 75);
  assert.equal(assessment.dimensions.programming.score, 58);
  assert.equal(assessment.dimensions.programming.ratingStatus, "insufficient");
  assert.equal(assessment.dimensions.programming.masteryLabel, "证据不足");
  assert.equal(assessment.dimensions.programming.evidenceCount, 4);
  assert.equal(assessment.dimensions.safety.score, null);
  assert.equal(assessment.dimensions.safety.masteryLabel, "待评估");
});

test("keeps a perfect small sample provisional instead of rating it as skilled", () => {
  const evidence = [{
    id: "small-sample-q1",
    attemptId: "small-sample-attempt",
    attemptNumber: 1,
    itemRevision: "small-sample-item",
    sourceType: "quiz",
    dimension: "programming",
    dimensionSource: "declared",
    topic: "G 代码",
    knowledgePoint: "G00 快速定位",
    knowledgePointId: "g00",
    correct: true,
    earned: 1,
    possible: 1,
    difficulty: "easy",
    occurredAt: "2026-08-19T08:00:00.000Z",
    sourceRefs: [],
    ragChunkIds: [],
    questionGrounded: false,
    reviewStatus: "auto_verified",
    objectiveIds: [],
  }];
  const result = calculateCapabilityAssessment(
    evidence,
    new Date("2026-08-19T08:00:00.000Z"),
  ).dimensions.programming;

  assert.equal(result.observedScore, 100);
  assert.equal(result.score, 60);
  assert.equal(result.ratingStatus, "insufficient");
  assert.equal(result.masteryLabel, "证据不足");
});

test("caps repeated exposure to the same item in formal capability scoring", () => {
  const common = {
    sourceType: "quiz",
    dimension: "safety",
    dimensionSource: "declared",
    topic: "急停操作",
    knowledgePoint: "异常时使用急停",
    knowledgePointId: "emergency-stop",
    itemRevision: "safety-item-v1",
    possible: 1,
    difficulty: "easy",
    occurredAt: "2026-08-19T08:00:00.000Z",
    sourceRefs: [],
    ragChunkIds: [],
    questionGrounded: false,
    reviewStatus: "auto_verified",
    objectiveIds: [],
  };
  const repeated = [
    { ...common, id: "repeat-1", attemptId: "attempt-1", attemptNumber: 1, correct: false, earned: 0 },
    { ...common, id: "repeat-2", attemptId: "attempt-2", attemptNumber: 2, correct: true, earned: 1 },
  ];
  const assessment = calculateCapabilityAssessment(
    repeated,
    new Date("2026-08-19T08:00:00.000Z"),
  );

  assert.equal(assessment.evidenceCount, 2);
  assert.equal(assessment.effectiveEvidenceCount, 1);
  assert.equal(assessment.dimensions.safety.observedScore, 0);
  assert.equal(assessment.dimensions.safety.ratingStatus, "insufficient");
});

test("keeps low-confidence AI subjective grading out of formal ratings", () => {
  const [evidence] = createQuizEvidence({
    attemptId: "subjective-low-confidence",
    topic: "异常处置",
    focus: "安全流程",
    difficulty: "medium",
    occurredAt: "2026-08-19T08:00:00.000Z",
    questions: [{
      questionId: "subjective-q1",
      question: {
        stem: "异常振动时如何处理？",
        options: [],
        answer: "停机并上报",
        question_type: "short_answer",
        capability_dimension: "safety",
        difficulty: "medium",
      },
      selectedAnswer: "我会停机",
      correctAnswer: "停机并上报",
      earned: 8,
      possible: 10,
      isCorrect: true,
      graderConfidence: 0.45,
    }],
  });
  const assessment = calculateCapabilityAssessment([evidence]);

  assert.equal(evidence.reviewStatus, "pending_review");
  assert.equal(assessment.evidenceCount, 1);
  assert.equal(assessment.effectiveEvidenceCount, 0);
  assert.equal(assessment.dimensions.safety.score, null);
});

test("persists capability evidence and removes subjective score controls", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, stateClient, server, model] = await Promise.all([
    readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
    readFile(new URL("lib/workspace-state-client.ts", projectRoot), "utf8"),
    readFile(
      new URL(
        "../agent/frontend_state.py",
        projectRoot,
      ),
      "utf8",
    ),
    readFile(new URL("lib/capability-assessment.ts", projectRoot), "utf8"),
  ]);

  assert.doesNotMatch(workspace, /className="score-slider"/);
  assert.doesNotMatch(workspace, /type="range"/);
  assert.match(workspace, /createQuizEvidence/);
  assert.match(workspace, /能力分数不接受主观建议/);
  assert.match(stateClient, /capability_assessment: CapabilityAssessmentSnapshot/);
  assert.match(server, /frontend_state/);
  assert.match(model, /DIFFICULTY_WEIGHT/);
  assert.match(model, /recencyWeight/);
  assert.match(model, /ragChunkIds/);
});

test("weights question difficulty and preserves RAG provenance", () => {
  const occurredAt = "2026-08-18T08:00:00.000Z";
  const evidence = createQuizEvidence({
    attemptId: "attempt-rag",
    topic: "数控机床安全操作",
    focus: "急停与异常处置",
    difficulty: "medium",
    occurredAt,
    response: {
      final_output: { evidence_refs: ["数控机床安全操作题库.xlsx"] },
      rag_package: {
        evidence: [
          {
            source_doc: "CQ-850电气说明书.pdf",
            chunk_id: "cq-850-p5-c2",
            score: 0.94,
          },
        ],
      },
    },
    questions: [
      {
        question: {
          stem: "出现紧急情况首先应该做什么？",
          options: ["急停", "继续加工"],
          answer: "A",
          explanation: "立即按下急停按钮。",
          difficulty: "easy",
          capability_dimension: "safety",
        },
        selectedAnswer: "A",
        correctAnswer: "A",
      },
      {
        question: {
          stem: "综合判断异常振动后的安全处置流程",
          options: ["停机检查", "提高转速"],
          answer: "A",
          explanation: "先停机并排查。",
          difficulty: "hard",
          capability_dimension: "safety",
        },
        selectedAnswer: "B",
        correctAnswer: "A",
      },
    ],
  });
  const assessment = calculateCapabilityAssessment(
    evidence,
    new Date(occurredAt),
  );
  const scores = assessmentToScoreMap(assessment, "beginner");

  assert.equal(assessment.dimensions.safety.observedScore, 40);
  assert.equal(assessment.dimensions.safety.score, 46);
  assert.equal(assessment.dimensions.safety.sourceCount, 2);
  assert.deepEqual(evidence[0].ragChunkIds, ["cq-850-p5-c2"]);
  assert.equal(scores.safety, 0);
  assert.equal(scores.safety_provisional, 46);
  assert.equal(scores.programming, 0);
});

test("persists an in-progress Quiz with draft and submitted answers", () => {
  const generatedAt = "2026-08-18T09:00:00.000Z";
  const session = createQuizSession({
    id: "quiz-session-test",
    courseId: "cnc_lathe",
    chapterId: "1.1",
    topic: "数控编程",
    focus: "G/M 指令与程序校验",
    difficulty: "medium",
    createdAt: generatedAt,
    questions: [
      {
        stem: "G00 的作用是什么？",
        options: ["快速定位", "直线插补"],
        answer: "A",
        explanation: "G00 用于快速定位。",
        difficulty: "medium",
        capability_dimension: "programming",
      },
      {
        stem: "程序运行前应做什么？",
        options: ["直接加工", "仿真校验"],
        answer: "B",
        explanation: "先进行仿真校验。",
        difficulty: "medium",
        capability_dimension: "programming",
      },
    ],
    response: {
      request_id: "req-test",
      final_output: { evidence_refs: ["数控车编程与操作.pdf"] },
      rag_package: {
        query: "G00 程序校验",
        confidence: 0.91,
        evidence: [
          {
            source_doc: "数控车编程与操作.pdf",
            chunk_id: "programming-c17",
          },
        ],
      },
    },
  });
  const firstQuestion = session.questions[0];
  const secondQuestion = session.questions[1];
  const withDraft = updateQuizDraft(session, firstQuestion.id, "A", generatedAt);
  const withSubmitted = submitQuizAnswer(
    withDraft,
    firstQuestion.id,
    "2026-08-18T09:01:00.000Z",
  );
  const withSecondDraft = updateQuizDraft(
    withSubmitted,
    secondQuestion.id,
    "B",
    "2026-08-18T09:02:00.000Z",
  );
  const [restored] = normalizeQuizSessions(
    JSON.parse(JSON.stringify([withSecondDraft])),
  );
  const progress = quizSessionProgress(restored);

  assert.equal(restored.status, "in_progress");
  assert.equal(restored.responses[firstQuestion.id].isCorrect, true);
  assert.equal(restored.responses[secondQuestion.id].submittedAt, null);
  assert.equal(restored.responses[secondQuestion.id].selectedAnswer, "B");
  assert.deepEqual(restored.retrieval.ragChunkIds, ["programming-c17"]);
  assert.equal(progress.submitted, 1);
  assert.equal(progress.correct, 1);
});

test("creates a 50-question Quiz blueprint with four types and all eight dimensions", () => {
  const blueprint = createQuizBlueprint(50, {
    theory: 50,
    safety: 28,
    operation: 60,
    programming: 42,
    foundations: 55,
    process_planning: 48,
    machining_operation: 62,
    quality_control: 57,
    maintenance: 35,
    advanced_manufacturing: 30,
  });
  const summary = summarizeQuizBlueprint(blueprint);

  assert.equal(blueprint.length, 50);
  assert.deepEqual(summary.byType, {
    single_choice: 22,
    true_false: 8,
    cloze: 10,
    short_answer: 10,
  });
  assert.deepEqual(summary.byDifficulty, { easy: 15, medium: 25, hard: 10 });
  assert.equal(Object.values(summary.byDimension).every((count) => count > 0), true);
  assert.deepEqual(
    blueprint.map((item) => item.questionType),
    [
      ...Array(22).fill("single_choice"),
      ...Array(8).fill("true_false"),
      ...Array(10).fill("cloze"),
      ...Array(10).fill("short_answer"),
    ],
  );
});

test("shows and persists Quiz batches while generation is still running", async () => {
  const source = await readFile(
    new URL("../components/LearningWorkspace.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /onSessionChange\(partialSession\)/);
  assert.match(source, /已生成 \$\{nextQuestions\.length\}\/\$\{blueprint\.length\} 题/);
  assert.match(source, /quiz-generation-banner/);
  assert.match(source, /const generationLock = useRef\(false\)/);
  assert.doesNotMatch(source, /key=\{activeQuizSessionId \|\| "quiz-empty"\}/);
});

test("normalizes true-false aliases to two explicit choices", () => {
  const normalized = normalizeTrueFalseQuestion({
    stem: "加工前可以不关闭防护门。",
    question_type: "true_false",
    options: ["Yes", "No", "不确定", "跳过"],
    answer: "No",
    explanation: "防护门属于安全联锁的一部分。",
    difficulty: "easy",
  });

  assert.deepEqual(normalized.options, ["正确", "错误"]);
  assert.equal(normalized.answer, "B");
  assert.equal(normalized.reference_answer, "错误");
});

test("renders visibly different concise and detailed explanations for legacy questions", () => {
  const question = {
    stem: "出现异常振动时应如何处理？",
    question_type: "short_answer",
    options: [],
    answer: "立即停止运行并上报。",
    reference_answer: "立即停止运行并上报。",
    explanation: "应先停止运行，避免风险继续扩大。随后按制度进行检查和上报。",
    difficulty: "medium",
    knowledge_point: "异常处置",
    scoring_rubric: {
      key_points: [{ description: "先停止运行", points: 5 }],
    },
  };

  const concise = quizExplanationText(question, "concise");
  const detailed = quizExplanationText(question, "detailed");
  assert.notEqual(concise, detailed);
  assert.match(detailed, /参考答案/);
  assert.match(detailed, /评分要点/);
});

test("persists a long subjective answer and partial semantic score", () => {
  const timestamp = "2026-08-19T08:00:00.000Z";
  const session = createQuizSession({
    id: "subjective-session",
    courseId: "cnc_lathe",
    chapterId: "1.1",
    topic: "安全异常处置",
    focus: "急停、断电和上报",
    difficulty: "hard",
    createdAt: timestamp,
    questions: [
      {
        stem: "发现异常振动后应如何处置？",
        question_type: "short_answer",
        options: [],
        answer: "立即停机，必要时急停，切断相关能源并上报。",
        reference_answer: "立即停机，必要时急停，切断相关能源并上报。",
        explanation: "先控制风险，再排查原因。",
        detailed_explanation: "异常振动可能扩大设备与人身风险，应先停止运行并按制度上报。",
        difficulty: "hard",
        points: 12,
        capability_dimension: "safety",
      },
    ],
    response: {
      request_id: "req-subjective",
      final_output: {},
      rag_package: null,
    },
  });
  const question = session.questions[0];
  const answer = "我会先停止程序并让主轴停转，情况紧急时按急停，然后隔离能源并通知负责人，不能带故障继续加工。";
  const draft = updateQuizDraft(session, question.id, answer, timestamp);
  const submitted = submitQuizAnswer(draft, question.id, {
    earnedPoints: 9.5,
    possiblePoints: 12,
    isCorrect: true,
    gradingMethod: "neural_embedding_rubric_agent",
    semanticSimilarity: 0.88,
    keyPointCoverage: 0.75,
    graderConfidence: 0.84,
    feedback: "主要处置步骤正确，可补充现场警戒。",
    matchedKeyPoints: ["停机", "隔离能源", "上报"],
    missedKeyPoints: ["现场警戒"],
    rubricVersion: "zlink-subjective-grader-v1",
  }, timestamp);
  const [restored] = normalizeQuizSessions(JSON.parse(JSON.stringify([submitted])));
  const progress = quizSessionProgress(restored);

  assert.equal(restored.responses[question.id].selectedAnswer, answer);
  assert.equal(restored.responses[question.id].earnedPoints, 9.5);
  assert.equal(restored.responses[question.id].semanticSimilarity, 0.88);
  assert.equal(progress.earnedPoints, 9.5);
  assert.equal(progress.possiblePoints, 12);
});

test("keeps Quiz history and RAG fields in the workspace snapshot", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, stateClient, server, quizModel] = await Promise.all([
    readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
    readFile(new URL("lib/workspace-state-client.ts", projectRoot), "utf8"),
    readFile(
      new URL(
        "../agent/frontend_state.py",
        projectRoot,
      ),
      "utf8",
    ),
    readFile(new URL("lib/quiz-session.ts", projectRoot), "utf8"),
  ]);

  assert.match(workspace, /Quiz 历史/);
  assert.match(workspace, /继续作答/);
  assert.match(workspace, /quiz_sessions: quizSessions\.slice/);
  assert.match(stateClient, /quiz_sessions: QuizSession\[\]/);
  assert.match(stateClient, /active_quiz_session_id: string/);
  assert.match(server, /workspace_state\.json/);
  assert.match(quizModel, /ragChunkIds/);
  assert.match(quizModel, /knowledgeBaseVersion/);
});

test("calculates job progress from evidence instead of the self-declared profile level", () => {
  const assessment = calculateCapabilityAssessment([]);
  const beginner = calculateLearningProgress({
    assessment,
    capabilityEvidence: [],
    profile: { background: "零基础", level: "beginner", preference: "步骤化" },
    chatQuestionCount: 0,
    memoryEventCount: 1,
    quizSessionCount: 0,
  });
  const selfDeclaredAdvanced = calculateLearningProgress({
    assessment,
    capabilityEvidence: [],
    profile: { background: "零基础", level: "advanced", preference: "步骤化" },
    chatQuestionCount: 0,
    memoryEventCount: 1,
    quizSessionCount: 0,
  });

  assert.equal(beginner.modelVersion, LEARNING_PROGRESS_MODEL_VERSION);
  assert.equal(beginner.currentStageId, "l1");
  assert.equal(beginner.overallProgress, selfDeclaredAdvanced.overallProgress);
  assert.equal(beginner.weightedMastery, 0);
  assert.match(beginner.blockers.join("\n"), /安全知识评价/);
});

test("does not treat Quiz-only evidence as practical job readiness", () => {
  const dimensions = [
    "safety",
    "foundations",
    "process_planning",
    "programming",
    "machining_operation",
    "quality_control",
    "maintenance",
    "advanced_manufacturing",
  ];
  const evidence = Array.from({ length: 56 }, (_, index) => ({
    id: `quiz-proof-${index}`,
    attemptId: `attempt-${Math.floor(index / 8)}`,
    sourceType: "quiz",
    dimension: dimensions[index % dimensions.length],
    topic: "岗位综合训练",
    knowledgePoint: `知识点 ${index}`,
    correct: true,
    earned: 1,
    possible: 1,
    difficulty: "hard",
    occurredAt: "2026-08-18T08:00:00.000Z",
    sourceRefs: ["数控车铣加工职业技能等级标准.pdf"],
    ragChunkIds: [`chunk-${index}`],
    attemptNumber: Math.floor(index / 8) + 1,
    itemRevision: `item-${index}`,
    knowledgePointId: `kp-${index}`,
    dimensionSource: "declared",
    questionGrounded: true,
    reviewStatus: "auto_verified",
    objectiveIds: [],
  }));
  const assessment = calculateCapabilityAssessment(
    evidence,
    new Date("2026-08-18T08:00:00.000Z"),
  );
  const progress = calculateLearningProgress({
    assessment,
    capabilityEvidence: evidence,
    profile: { background: "机械专业", level: "advanced", preference: "案例" },
    chatQuestionCount: 10,
    memoryEventCount: 10,
    quizSessionCount: 7,
    courseProgress: [],
  });

  assert.equal(progress.evidence.quizEvidenceCount, 56);
  assert.equal(progress.evidence.practicalEvidenceCount, 0);
  assert.equal(progress.currentStageId, "l1");
  assert.match(progress.blockers.join("\n"), /已审核实操能力|可评级实操维度/);
});

test("persists learning progress and forwards it to Memory, RAG and the orchestrator", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, stateClient, contract, server, state, domainContext] =
    await Promise.all([
      readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
      readFile(new URL("lib/workspace-state-client.ts", projectRoot), "utf8"),
      readFile(new URL("lib/agent-contract.ts", projectRoot), "utf8"),
      readFile(
        new URL(
          "../agent/api.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/state.py",
          projectRoot,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../agent/node/knowledge_generation/progress_branch_nodes.py",
          projectRoot,
        ),
        "utf8",
      ),
    ]);

  assert.match(workspace, /label: "学习进度"/);
  assert.match(workspace, /learning_progress: learningProgress/);
  assert.match(workspace, /learning_progress: learningProgress\.agentContext/);
  assert.match(workspace, /生成下一步训练方案/);
  assert.match(stateClient, /learning_progress: LearningProgressResult/);
  assert.match(contract, /learning_progress\?: Record<string, unknown>/);
  assert.match(server, /get_learning_progress/);
  assert.match(state, /learning_progress: dict\[str, Any\]/);
  assert.match(domainContext, /learning_progress/);
});

test("creates a grounded lecture and assesses mastery only from later evidence", () => {
  const response = {
    api_version: "v1",
    request_id: "req-lecture-test",
    status: "success",
    content_type: "lecture",
    task: "生成机床加工基本概念讲义",
    final_output: {
      title: "机床加工基本概念",
      summary: "面向零基础学习者的入门讲义。",
      payload: {
        sections: [
          { heading: "学习目标", content: "理解机床加工的基本作用。" },
          { heading: "核心概念", content: "机床通过受控运动完成材料去除。" },
        ],
      },
      evidence_refs: ["数控车编程与操作.pdf"],
    },
    rag_package: {
      confidence: 0.9,
      knowledge_base_version: "resource-v1",
      evidence: [
        {
          source_doc: "数控车编程与操作.pdf",
          chunk_id: "cnc-basic-1",
        },
      ],
    },
    check_report: null,
    safety_report: null,
    profile_update_suggestions: {},
    agent_trace: [],
    error_type: null,
    retry_count: 0,
  };
  const baseline = [
    {
      id: "old-proof",
      attemptId: "old-attempt",
      sourceType: "quiz",
      dimension: "foundations",
      topic: "旧测验",
      knowledgePoint: "旧知识点",
      correct: true,
      earned: 1,
      possible: 1,
      difficulty: "easy",
      occurredAt: "2026-08-18T08:00:00.000Z",
      sourceRefs: [],
      ragChunkIds: [],
    },
  ];
  const lecture = createLectureSession({
    id: "lecture-test",
    courseId: "cnc_lathe",
    chapterId: "1.1",
    response,
    capabilityEvidence: baseline,
    generationReason: "initial",
    createdAt: "2026-08-18T09:00:00.000Z",
  });
  const before = calculateLectureMastery(lecture, baseline);
  const later = Array.from({ length: 8 }, (_, index) => ({
    ...baseline[0],
    id: `new-proof-${index}`,
    attemptId: index < 4 ? "new-attempt-1" : "new-attempt-2",
    attemptNumber: index < 4 ? 1 : 2,
    itemRevision: `lecture-item-${index}`,
    topic: "机床加工基本概念",
    knowledgePoint: `新知识点 ${index % 4}`,
    knowledgePointId: `lecture-kp-${index % 4}`,
    correct: index !== 7,
    earned: index !== 7 ? 1 : 0,
    occurredAt: "2026-08-18T10:00:00.000Z",
    sourceRefs: ["数控车编程与操作.pdf"],
    ragChunkIds: [`cnc-basic-${index}`],
    dimensionSource: "declared",
    questionGrounded: true,
    reviewStatus: "auto_verified",
    lectureId: lecture.id,
    chapterId: lecture.chapterId,
    objectiveIds: lecture.objectiveIds,
  }));
  const after = calculateLectureMastery(lecture, [...baseline, ...later]);

  assert.equal(lecture.sections.length, 2);
  assert.deepEqual(lecture.sourceRefs, ["数控车编程与操作.pdf"]);
  assert.equal(before.status, "not_assessed");
  assert.equal(after.status, "mastered");
  assert.equal(after.weightedAccuracy, 0.875);
  assert.equal(after.recommendedForNextStage, true);
  assert.match(after.message, /进一步进行学习/);
});

test("normalizes saved lecture history and wires confirmation, persistence and RAG", async () => {
  const projectRoot = new URL("../", import.meta.url);
  const [workspace, stateClient, server, lectureModel] = await Promise.all([
    readFile(new URL("components/LearningWorkspace.tsx", projectRoot), "utf8"),
    readFile(new URL("lib/workspace-state-client.ts", projectRoot), "utf8"),
    readFile(
      new URL(
        "../agent/frontend_state.py",
        projectRoot,
      ),
      "utf8",
    ),
    readFile(new URL("lib/lecture-session.ts", projectRoot), "utf8"),
  ]);

  assert.deepEqual(normalizeLectureSessions([]), []);
  assert.match(workspace, /label: "学习讲义"/);
  assert.match(workspace, /重新生成/);
  assert.match(workspace, /生成下阶段讲义/);
  assert.match(workspace, /仍然生成下阶段讲义/);
  assert.match(workspace, /lecture_sessions: lectureSessions\.slice/);
  assert.match(workspace, /contentType: "lecture"/);
  assert.match(stateClient, /lecture_sessions: LectureSession\[\]/);
  assert.match(server, /workspace_state\.json/);
  assert.match(lectureModel, /baselineEvidenceIds/);
  assert.match(lectureModel, /sourceRefs/);
  assert.match(lectureModel, /recommendedForNextStage/);
});
