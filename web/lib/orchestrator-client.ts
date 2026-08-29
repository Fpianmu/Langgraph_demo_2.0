"use client";

import type {
  AgentRequest,
  AgentResponse,
  AgentTrace,
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

type RunEvent = {
  event_id?: string;
  event_type?: string;
  node_id?: string;
  agent_id?: string;
  agent_display_name?: string;
  from_agent?: string;
  to_agent?: string;
  display_text?: string;
  detail?: string;
};

function errorMessage(value: unknown, fallback: string): string {
  if (!value || typeof value !== "object") return fallback;
  const record = value as Record<string, unknown>;
  return String(record.error || record.detail || fallback);
}

function parseEvent(event: MessageEvent<string>): RunEvent | null {
  try {
    const parsed = JSON.parse(event.data) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as RunEvent) : null;
  } catch {
    return null;
  }
}

function traceFromEvent(event: RunEvent): AgentTrace | null {
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
  for (;;) {
    const response = await fetch(
      `/api/graph/runs/${encodeURIComponent(runId)}/result`,
      { cache: "no-store", signal },
    );
    const data = (await response.json()) as Record<string, unknown>;
    if (response.status === 202) {
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      continue;
    }
    if (!response.ok) {
      throw new Error(errorMessage(data, `读取任务结果失败（HTTP ${response.status}）`));
    }
    const result =
      data.result && typeof data.result === "object"
        ? (data.result as Record<string, unknown>)
        : data;
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
}

export async function dispatchToCentralOrchestrator(
  request: AgentRequest,
  onTrace?: (trace: AgentTrace[]) => void,
): Promise<AgentResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 5 * 60_000);
  let source: EventSource | null = null;

  try {
    const response = await fetch("/api/graph/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    const data = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(errorMessage(data, `中央调度器返回 HTTP ${response.status}`));
    }
    const runId = typeof data.run_id === "string" ? data.run_id : "";
    if (!runId) throw new Error("第二版中央调度器没有返回 run_id");

    const liveTrace: AgentTrace[] = [];
    const seen = new Set<string>();
    await new Promise<void>((resolve, reject) => {
      source = new EventSource(
        `/api/graph/runs/${encodeURIComponent(runId)}/events`,
      );
      const receive = (message: Event) => {
        const runEvent = parseEvent(message as MessageEvent<string>);
        if (!runEvent) return;
        if (runEvent.event_id && seen.has(runEvent.event_id)) return;
        if (runEvent.event_id) seen.add(runEvent.event_id);
        const item = traceFromEvent(runEvent);
        if (item) {
          liveTrace.push(item);
          onTrace?.([...liveTrace]);
        }
      };
      source.addEventListener("run.started", receive);
      source.addEventListener("agent.activity", receive);
      source.addEventListener("agent.message", receive);
      source.addEventListener("run.completed", (message) => {
        receive(message);
        source?.close();
        resolve();
      });
      source.addEventListener("run.failed", (message) => {
        const runEvent = parseEvent(message as MessageEvent<string>);
        source?.close();
        reject(new Error(runEvent?.detail || "中央调度器执行失败"));
      });
      source.onerror = () => {
        if (controller.signal.aborted) {
          source?.close();
          reject(new DOMException("Aborted", "AbortError"));
        }
        // EventSource reconnects automatically and sends Last-Event-ID.  The
        // backend replays missed events, so a transient disconnect is safe.
      };
      controller.signal.addEventListener(
        "abort",
        () => {
          source?.close();
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
    return await readRunResult(runId, request, liveTrace, controller.signal);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("中央调度器响应超时，请检查多 Agent 服务");
    }
    throw error;
  } finally {
    source?.close();
    window.clearTimeout(timer);
  }
}
