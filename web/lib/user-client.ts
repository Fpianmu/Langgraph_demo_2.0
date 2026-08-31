export type UserSummary = {
  user_id: string;
  display_name?: string | null;
  background_type?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type OnboardingQuestion = {
  id: string;
  stem: string;
  question_type: "single_choice" | string;
  options: string[];
  capability_dimension: string;
  knowledge_points: Array<{ id: string; name: string; weight?: number }>;
  difficulty: string;
  points: number;
};

export type OnboardingAssessment = {
  assessment_id: string;
  course_id: string;
  status: string;
  created_at: string;
  questions: OnboardingQuestion[];
};

export type OnboardingResult = {
  assessment_id: string;
  course_id: string;
  status: "scored" | string;
  overall_score: number;
  learner_level: string;
  dimension_scores: Record<string, number>;
  metrics: Record<string, number>;
  scored_items: Array<Record<string, unknown>>;
  capability_evidence: Array<Record<string, unknown>>;
  knowledge_gap_patches: Array<Record<string, unknown>>;
  path_assignment: Record<string, unknown>;
  profile_update_suggestions: Record<string, unknown>;
};

export type RegisteredUser = UserSummary & {
  status: string;
  assessment_result?: OnboardingResult;
  profile_context?: Record<string, unknown>;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const detail = payload.detail || payload.error || `请求失败（HTTP ${response.status}）`;
    throw new Error(String(detail));
  }
  return payload as T;
}

export async function listUsers(): Promise<UserSummary[]> {
  const result = await requestJson<{ users?: UserSummary[] }>("/api/users");
  return Array.isArray(result.users) ? result.users : [];
}

export function createOnboardingAssessment(
  courseId = "cnc_lathe",
): Promise<OnboardingAssessment> {
  return requestJson("/api/onboarding/assessments", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId }),
  });
}

export function submitOnboardingAssessment(
  assessmentId: string,
  answers: Array<{ question_id: string; answer: string }>,
): Promise<OnboardingResult> {
  return requestJson(
    `/api/onboarding/assessments/${encodeURIComponent(assessmentId)}/submit`,
    {
      method: "POST",
      body: JSON.stringify({ answers }),
    },
  );
}

export function createRegisteredUser(input: {
  user_id: string;
  display_name: string;
  background_type: string;
  assessment_result: OnboardingResult;
}): Promise<RegisteredUser> {
  return requestJson("/api/users", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
