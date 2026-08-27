import type { LearnerProfile, ScoreMap } from "@/lib/agent-contract";
import type { BackendProfile } from "@/lib/profile-client";
import type { CapabilityAssessmentSnapshot } from "@/lib/capability-assessment";
import type { QuizSession } from "@/lib/quiz-session";
import type { LearningProgressResult } from "@/lib/learning-progress";
import type { LectureSession } from "@/lib/lecture-session";

export type PersistedChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  followUps?: string[];
};

export type PersistedMemoryEvent = {
  id: string;
  title: string;
  detail: string;
  time: string;
};

export type PersistedUserIdentity = {
  nickname: string;
  avatarId: string;
};

export type FrontendStateSnapshot = {
  state_version: 1;
  qa_context_version: string;
  messages: PersistedChatMessage[];
  history: string[];
  memory_events: PersistedMemoryEvent[];
  pending_suggestions: unknown[];
  user_identity: PersistedUserIdentity;
  qa_session_id: string;
  capability_assessment: CapabilityAssessmentSnapshot;
  quiz_sessions: QuizSession[];
  active_quiz_session_id: string;
  learning_progress: LearningProgressResult;
  lecture_sessions: LectureSession[];
  active_lecture_session_id: string;
};

export type BackendWorkspaceState = BackendProfile & {
  frontend_state?: Partial<FrontendStateSnapshot>;
  client_revision?: number;
  state_updated_at?: string | null;
};

export type WorkspaceStateUpdate = {
  profile: LearnerProfile;
  scores: ScoreMap;
  frontend_state: FrontendStateSnapshot;
  client_revision: number;
};

async function stateRequest(
  userId: string,
  init?: RequestInit,
): Promise<BackendWorkspaceState> {
  const response = await fetch(`/api/state/${encodeURIComponent(userId)}`, {
    ...init,
    cache: "no-store",
  });
  const data = (await response.json()) as BackendWorkspaceState & {
    error?: string;
  };
  if (!response.ok) {
    const error = new Error(data.error || `持久化接口返回 HTTP ${response.status}`);
    Object.assign(error, { status: response.status });
    throw error;
  }
  return data;
}

export function loadBackendWorkspaceState(
  userId: string,
): Promise<BackendWorkspaceState> {
  return stateRequest(userId);
}

export function saveBackendWorkspaceState(
  userId: string,
  payload: WorkspaceStateUpdate,
): Promise<BackendWorkspaceState> {
  const send = (body: unknown) =>
    stateRequest(userId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  return send(payload).catch((error: Error & { status?: number }) => {
    if (error.status !== 422) throw error;
    // Compatibility fallback for a teammate's older v1 server that has not
    // added capability_assessment yet. Evidence remains in localStorage and
    // will start syncing as soon as that optional backend field is deployed.
    const legacyFrontendState = Object.fromEntries(
      Object.entries(payload.frontend_state).filter(
        ([key]) =>
          key !== "capability_assessment" &&
          key !== "quiz_sessions" &&
          key !== "active_quiz_session_id" &&
          key !== "learning_progress" &&
          key !== "lecture_sessions" &&
          key !== "active_lecture_session_id",
      ),
    );
    return send({
      ...payload,
      frontend_state: legacyFrontendState,
    });
  });
}
