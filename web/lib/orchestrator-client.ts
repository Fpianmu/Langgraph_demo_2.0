"use client";

import type {
  AgentRequest,
  AgentResponse,
  AgentTrace,
  OrchestratorInput,
} from "@/lib/agent-contract";
import {
  createGraphRun,
  readGraphRunResult,
  streamGraphRunEvents,
  type GraphRunEvent,
  type GraphRunStatus,
} from "@/lib/graph-run-client";

function requestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `req_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  }
  return `req_${Date.now().toString(36)}`;
}

export function buildAgentRequest(input: OrchestratorInput): AgentRequest {
  return {
    api_version: "v2",
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
    quiz_blueprint_input: input.quizBlueprint,
    profile_md_version: new Date().toISOString().slice(0, 10),
    qa_session_id: input.qaSessionId,
    options: {
      max_retries: 3,
      trace_level: "debug",
      return_rag_package: true,
    },
  };
}

export type OrchestratorRunCallbacks = {
  onTrace?: (trace: AgentTrace[]) => void;
  onEvent?: (event: GraphRunEvent) => void;
  onRunCreated?: (runId: string) => void;
  onStatus?: (status: GraphRunStatus) => void;
};

function traceFromEvent(event: GraphRunEvent): AgentTrace | null {
  if (event.event_type === "agent.activity") {
    return {
      node: String(event.node_id || event.agent_id || "agent"),
      status: "success",
      summary: String(event.display_text || event.detail || "Agent 已完成当前步骤"),
    };
  }
  if (event.event_type === "agent.message") {
    return {
      node: `${event.from_agent || "agent"} → ${event.to_agent || "agent"}`,
      status: "success",
      summary: String(event.display_text || event.detail || "任务已移交下一 Agent"),
    };
  }
  return null;
}

async function readRunResult(
  runId: string,
  request: AgentRequest,
  liveTrace: AgentTrace[],
  signal: AbortSignal,
): Promise<AgentResponse> {
  const result = await readGraphRunResult(runId, signal);
  if (String(result.request_id || request.request_id) !== request.request_id) {
    throw new Error("返回的 request_id 与当前请求不一致");
  }
  return {
    ...(result as Partial<AgentResponse>),
    api_version: "v2",
    request_id: request.request_id,
    status: (result.status || "success") as AgentResponse["status"],
    content_type: (result.content_type || request.content_type) as AgentResponse["content_type"],
    task: String(result.task || request.task || request.raw_prompt),
    final_output:
      result.final_output && typeof result.final_output === "object"
        ? (result.final_output as AgentResponse["final_output"])
        : null,
    rag_package:
      result.rag_package && typeof result.rag_package === "object"
        ? (result.rag_package as AgentResponse["rag_package"])
        : null,
    check_report:
      result.check_report && typeof result.check_report === "object"
        ? (result.check_report as AgentResponse["check_report"])
        : null,
    safety_report:
      result.safety_report && typeof result.safety_report === "object"
        ? (result.safety_report as AgentResponse["safety_report"])
        : null,
    profile_update_suggestions:
      result.profile_update_suggestions &&
      typeof result.profile_update_suggestions === "object"
        ? (result.profile_update_suggestions as AgentResponse["profile_update_suggestions"])
        : {},
    agent_trace: Array.isArray(result.agent_trace)
      ? (result.agent_trace as AgentTrace[])
      : liveTrace,
    error_type: typeof result.error_type === "string" ? result.error_type : null,
    retry_count: Number(result.retry_count || 0),
  };
}

export async function dispatchToCentralOrchestrator(
  request: AgentRequest,
  callbacks: OrchestratorRunCallbacks = {},
): Promise<AgentResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 5 * 60_000);

  try {
    const { runId, status } = await createGraphRun(request, controller.signal);
    callbacks.onRunCreated?.(runId);
    callbacks.onStatus?.(status);

    const liveTrace: AgentTrace[] = [];
    const terminalStatus = await streamGraphRunEvents(
      runId,
      (runEvent) => {
        callbacks.onEvent?.(runEvent);
        const item = traceFromEvent(runEvent);
        if (item) {
          liveTrace.push(item);
          callbacks.onTrace?.([...liveTrace]);
        }
      },
      { signal: controller.signal, onStatus: callbacks.onStatus },
    );
    if (terminalStatus !== "completed") {
      throw new Error(
        `中央调度器任务${terminalStatus === "cancelled" ? "已取消" : "未完成"}`,
      );
    }
    return await readRunResult(runId, request, liveTrace, controller.signal);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("中央调度器响应超时，请检查多 Agent 服务");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}
