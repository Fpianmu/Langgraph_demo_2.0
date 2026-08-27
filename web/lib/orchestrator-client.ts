"use client";

import type {
  AgentRequest,
  AgentResponse,
  OrchestratorInput,
} from "@/lib/agent-contract";

function requestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `req_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  }
  return `req_${Date.now().toString(36)}`;
}

export function buildAgentRequest(input: OrchestratorInput): AgentRequest {
  return {
    api_version: "v1",
    request_id: requestId(),
    user_id: input.userId,
    course_id: input.courseId,
    chapter_id: input.chapterId,
    raw_prompt: input.prompt,
    task: input.task || input.prompt,
    content_type: input.contentType,
    latest_scores: input.scores,
    learner_profile: input.profile,
    learning_progress: input.learningProgress,
    // The backend resolves the real profile path from user_id. Sending a
    // deeptutor:// pseudo path prevents the teammate backend from loading its
    // repository-backed Memory file.
    profile_md_version: new Date().toISOString().slice(0, 10),
    qa_session_id: input.qaSessionId,
    options: {
      max_retries: 3,
      trace_level: "debug",
      return_rag_package: true,
    },
  };
}

function isAgentResponse(value: unknown): value is AgentResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<AgentResponse>;
  return (
    candidate.api_version === "v1" &&
    typeof candidate.request_id === "string" &&
    typeof candidate.status === "string" &&
    Array.isArray(candidate.agent_trace)
  );
}

export async function dispatchToCentralOrchestrator(
  request: AgentRequest,
): Promise<AgentResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 90_000);

  try {
    const response = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    const data = (await response.json()) as unknown;

    if (!response.ok) {
      const message =
        data && typeof data === "object" && "error" in data
          ? String((data as { error: unknown }).error)
          : `中央调度器返回 HTTP ${response.status}`;
      throw new Error(message);
    }
    if (!isAgentResponse(data)) {
      throw new Error("中央调度器返回的数据不符合 v1 契约");
    }
    if (data.request_id !== request.request_id) {
      throw new Error("返回的 request_id 与当前请求不一致");
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("中央调度器响应超时，请检查多 Agent 服务");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}
