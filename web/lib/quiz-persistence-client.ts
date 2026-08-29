"use client";

import type { CapabilityEvidence } from "./capability-assessment.ts";
import type { QuizSession } from "./quiz-session.ts";

type QuizSubmitResult = {
  attempt_id?: string;
  artifact_id?: string;
  feedback_source_ids?: Record<string, unknown>;
};

function errorMessage(value: unknown, fallback: string): string {
  if (!value || typeof value !== "object") return fallback;
  const record = value as Record<string, unknown>;
  return String(record.error || record.detail || fallback);
}

export async function submitPersistedQuizAttempts(
  userId: string,
  session: QuizSession,
): Promise<QuizSubmitResult[]> {
  const groups = new Map<string, Array<{ question_id: string; user_answer: string }>>();
  for (const question of session.questions) {
    const artifactId = question.backend_artifact_id || "";
    const questionId = question.backend_question_id || "";
    const response = session.responses[question.id];
    if (!artifactId || !questionId || !response?.submittedAt) continue;
    const group = groups.get(artifactId) || [];
    group.push({ question_id: questionId, user_answer: response.selectedAnswer });
    groups.set(artifactId, group);
  }

  const results: QuizSubmitResult[] = [];
  for (const [artifactId, answers] of groups) {
    const response = await fetch("/api/quiz-submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        course_id: session.courseId,
        chapter_id: session.chapterId,
        artifact_id: artifactId,
        answers,
      }),
    });
    const data = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(errorMessage(data, `Quiz 作答保存失败（HTTP ${response.status}）`));
    }
    results.push(data as QuizSubmitResult);
  }
  return results;
}

export async function syncQuizProfileEvidence(
  userId: string,
  courseId: string,
  evidence: CapabilityEvidence[],
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/storage/users/${encodeURIComponent(userId)}/quiz-evidence`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: `quiz_sync_${Date.now().toString(36)}`,
        course_id: courseId,
        capability_evidence: evidence,
      }),
    },
  );
  const data = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(errorMessage(data, `Quiz 能力证据同步失败（HTTP ${response.status}）`));
  }
  return data;
}
