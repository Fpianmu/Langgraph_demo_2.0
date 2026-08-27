"use client";

import type { QuizSessionQuestion, QuizGradingResult } from "./quiz-session.ts";

type GradeResponse = {
  earned_score: number;
  max_score: number;
  is_correct: boolean;
  grading_method: string;
  semantic_similarity?: number | null;
  key_point_coverage?: number | null;
  grader_confidence?: number | null;
  feedback?: string;
  matched_key_points?: string[];
  missed_key_points?: string[];
  grading_version?: string;
  factuality_score?: number | null;
  contradictions?: string[];
  safety_critical_error?: boolean;
  rubric_point_scores?: Array<{ index: number; score: number }>;
};

export async function gradeSubjectiveQuizAnswer(input: {
  question: QuizSessionQuestion;
  userAnswer: string;
  userId: string;
  courseId: string;
}): Promise<QuizGradingResult> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 90_000);
  let response: Response;
  try {
    response = await fetch("/api/quiz-grade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
      user_id: input.userId,
      course_id: input.courseId,
      question_id: input.question.id,
      question_type: input.question.question_type,
      question: input.question.stem,
      user_answer: input.userAnswer,
      reference_answer:
        input.question.reference_answer || input.question.answer,
      max_score: input.question.points,
      difficulty: input.question.difficulty,
      capability_dimension: input.question.capability_dimension,
      knowledge_point: input.question.knowledge_point,
      scoring_rubric: input.question.scoring_rubric || {},
      source_refs: input.question.source_refs || [],
      rag_chunk_ids: input.question.rag_chunk_ids || [],
      }),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("主观题评分超时，请保留答案后重试");
    }
    throw new Error("无法连接主观题评分服务，请确认中央调度器已启动");
  } finally {
    window.clearTimeout(timer);
  }

  const raw = await response.text();
  let data: GradeResponse & { error?: string; detail?: string };
  try {
    data = raw ? (JSON.parse(raw) as typeof data) : ({} as typeof data);
  } catch {
    data = {} as typeof data;
  }
  if (!response.ok) {
    const upstreamMessage = data.error || data.detail;
    const restartHint = response.status === 404
      ? "。当前后端尚未加载评分接口，请关闭知链启动窗口后重新运行“启动前端.cmd”"
      : "";
    throw new Error(
      (upstreamMessage || raw.slice(0, 240) || `主观题评分服务返回 HTTP ${response.status}`) +
        restartHint,
    );
  }
  return {
    earnedPoints: Number(data.earned_score || 0),
    possiblePoints: Number(data.max_score || input.question.points || 1),
    isCorrect: !!data.is_correct,
    gradingMethod: data.grading_method || "unknown",
    semanticSimilarity: Number.isFinite(Number(data.semantic_similarity))
      ? Number(data.semantic_similarity)
      : null,
    keyPointCoverage: Number.isFinite(Number(data.key_point_coverage))
      ? Number(data.key_point_coverage)
      : null,
    graderConfidence: Number.isFinite(Number(data.grader_confidence))
      ? Number(data.grader_confidence)
      : null,
    feedback: data.feedback || "",
    matchedKeyPoints: data.matched_key_points || [],
    missedKeyPoints: data.missed_key_points || [],
    rubricVersion: data.grading_version || "zlink-subjective-grader-v1",
    factualityScore: Number.isFinite(Number(data.factuality_score))
      ? Number(data.factuality_score)
      : null,
    contradictions: data.contradictions || [],
    safetyCriticalError: data.safety_critical_error === true,
    rubricPointScores: data.rubric_point_scores || [],
  };
}
