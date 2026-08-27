import type { LearnerProfile, ScoreMap } from "@/lib/agent-contract";

export type BackendProfile = {
  profile?: Partial<LearnerProfile>;
  metrics?: Record<string, number>;
  profile_md_ref?: string;
  profile_md_hash?: string;
  knowledge_gaps?: Array<Record<string, unknown>>;
  learning_progress?: Array<Record<string, unknown>>;
};

export type BackendHealth = {
  status: string;
  model_configured: boolean;
  error?: string;
};

export async function checkBackendHealth(): Promise<BackendHealth> {
  const response = await fetch("/api/agent/health", { cache: "no-store" });
  const data = (await response.json()) as BackendHealth;
  if (!response.ok) {
    throw new Error(data.error || "无法连接多 Agent 中央调度器");
  }
  return data;
}

async function profileRequest(
  userId: string,
  init?: RequestInit,
): Promise<BackendProfile> {
  const response = await fetch(`/api/profile/${encodeURIComponent(userId)}`, init);
  const data = (await response.json()) as BackendProfile & { error?: string };
  if (!response.ok) {
    throw new Error(data.error || `Memory 接口返回 HTTP ${response.status}`);
  }
  return data;
}

export function loadBackendProfile(userId: string): Promise<BackendProfile> {
  return profileRequest(userId);
}

export function saveBackendProfile(
  userId: string,
  profile: LearnerProfile,
  scores: ScoreMap,
): Promise<BackendProfile> {
  return profileRequest(userId, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile, scores }),
  });
}

export function mergeBackendProfile(
  data: BackendProfile,
  currentProfile: LearnerProfile,
  currentScores: ScoreMap,
): { profile: LearnerProfile; scores: ScoreMap } {
  const remoteProfile = data.profile || {};
  const level = remoteProfile.level;
  const profile: LearnerProfile = {
    ...currentProfile,
    ...(typeof remoteProfile.background === "string"
      ? { background: remoteProfile.background }
      : {}),
    ...(level === "beginner" || level === "intermediate" || level === "advanced"
      ? { level }
      : {}),
    ...(typeof remoteProfile.preference === "string"
      ? { preference: remoteProfile.preference }
      : {}),
  };
  const metrics = data.metrics || {};
  const scores: ScoreMap = {
    ...currentScores,
    theory: Number(metrics.theory_score ?? currentScores.theory),
    safety: Number(metrics.safety_score ?? currentScores.safety),
    operation: Number(metrics.operation_score ?? currentScores.operation),
  };
  return { profile, scores };
}
