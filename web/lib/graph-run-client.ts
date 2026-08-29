"use client";

export type GraphRunStatus =
  | "idle"
  | "created"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type GraphPayloadRefs = Record<string, unknown>;

type GraphRunEventBase = {
  event_id?: string;
  run_id?: string;
  created_at?: string;
  detail?: string;
  display_text?: string;
  payload_refs?: GraphPayloadRefs;
};

export type GraphRunStartedEvent = GraphRunEventBase & {
  event_type: "run.started";
};

export type GraphRunCompletedEvent = GraphRunEventBase & {
  event_type: "run.completed";
  result_url?: string;
};

export type GraphRunFailedEvent = GraphRunEventBase & {
  event_type: "run.failed";
};

export type GraphRunCancelledEvent = GraphRunEventBase & {
  event_type: "run.cancelled";
};

export type AgentActivityEvent = GraphRunEventBase & {
  event_type: "agent.activity";
  agent_id?: string;
  agent_display_name?: string;
  node_id?: string;
};

export type AgentMessageEvent = GraphRunEventBase & {
  event_type: "agent.message";
  from_agent?: string;
  to_agent?: string;
  message_type?: string;
};

export type GraphRunEvent =
  | GraphRunStartedEvent
  | GraphRunCompletedEvent
  | GraphRunFailedEvent
  | GraphRunCancelledEvent
  | AgentActivityEvent
  | AgentMessageEvent;

export type GraphRunState = {
  run_id: string;
  status: Exclude<GraphRunStatus, "idle">;
  event_count: number;
  result_url?: string | null;
  error?: string | null;
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function apiError(value: unknown, fallback: string): string {
  const data = record(value);
  return data ? String(data.error || data.detail || fallback) : fallback;
}

async function responseJson(response: Response): Promise<Record<string, unknown>> {
  try {
    return record(await response.json()) ?? {};
  } catch {
    return {};
  }
}

export async function createGraphRun(
  payload: unknown,
  signal?: AbortSignal,
): Promise<{ runId: string; status: Exclude<GraphRunStatus, "idle"> }> {
  const response = await fetch("/api/graph/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  const data = await responseJson(response);
  if (!response.ok) {
    throw new Error(apiError(data, `中央调度器返回 HTTP ${response.status}`));
  }
  const runId = typeof data.run_id === "string" ? data.run_id : "";
  if (!runId) throw new Error("第二版中央调度器没有返回 run_id");
  const status = String(data.status || "created") as Exclude<GraphRunStatus, "idle">;
  return { runId, status };
}

export async function getGraphRunState(
  runId: string,
  signal?: AbortSignal,
): Promise<GraphRunState> {
  const response = await fetch(`/api/graph/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
    signal,
  });
  const data = await responseJson(response);
  if (!response.ok) {
    throw new Error(apiError(data, `读取任务状态失败（HTTP ${response.status}）`));
  }
  return {
    run_id: String(data.run_id || runId),
    status: String(data.status || "running") as GraphRunState["status"],
    event_count: Number(data.event_count || 0),
    result_url: typeof data.result_url === "string" ? data.result_url : null,
    error: typeof data.error === "string" ? data.error : null,
  };
}

export async function readGraphRunResult(
  runId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  for (;;) {
    const response = await fetch(
      `/api/graph/runs/${encodeURIComponent(runId)}/result`,
      { cache: "no-store", signal },
    );
    const data = await responseJson(response);
    if (response.status === 202) {
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      continue;
    }
    if (!response.ok) {
      throw new Error(apiError(data, `读取任务结果失败（HTTP ${response.status}）`));
    }
    return record(data.result) ?? data;
  }
}

export async function cancelGraphRun(runId: string): Promise<GraphRunState> {
  const response = await fetch(
    `/api/graph/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
  const data = await responseJson(response);
  if (!response.ok) {
    throw new Error(apiError(data, `取消任务失败（HTTP ${response.status}）`));
  }
  return {
    run_id: String(data.run_id || runId),
    status: String(data.status || "cancelled") as GraphRunState["status"],
    event_count: Number(data.event_count || 0),
    error: typeof data.error === "string" ? data.error : null,
  };
}

function parseGraphRunEvent(event: MessageEvent<string>): GraphRunEvent | null {
  try {
    const data = record(JSON.parse(event.data));
    if (!data || typeof data.event_type !== "string") return null;
    return data as GraphRunEvent;
  } catch {
    return null;
  }
}

export function streamGraphRunEvents(
  runId: string,
  onEvent: (event: GraphRunEvent) => void,
  options: {
    signal?: AbortSignal;
    onStatus?: (status: GraphRunStatus) => void;
  } = {},
): Promise<GraphRunStatus> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(
      `/api/graph/runs/${encodeURIComponent(runId)}/events`,
    );
    const seen = new Set<string>();
    let settled = false;

    const abort = () =>
      finish("cancelled", new DOMException("Aborted", "AbortError"));
    const finish = (status: GraphRunStatus, error?: Error) => {
      if (settled) return;
      settled = true;
      source.close();
      options.signal?.removeEventListener("abort", abort);
      options.onStatus?.(status);
      if (error) reject(error);
      else resolve(status);
    };

    const receive = (message: Event) => {
      const graphEvent = parseGraphRunEvent(message as MessageEvent<string>);
      if (!graphEvent) return;
      if (graphEvent.event_id && seen.has(graphEvent.event_id)) return;
      if (graphEvent.event_id) seen.add(graphEvent.event_id);
      onEvent(graphEvent);

      if (graphEvent.event_type === "run.started") {
        options.onStatus?.("running");
      } else if (graphEvent.event_type === "run.completed") {
        finish("completed");
      } else if (graphEvent.event_type === "run.cancelled") {
        finish("cancelled");
      } else if (graphEvent.event_type === "run.failed") {
        finish("failed", new Error(graphEvent.detail || "中央调度器执行失败"));
      }
    };

    for (const eventType of [
      "run.started",
      "agent.activity",
      "agent.message",
      "run.completed",
      "run.failed",
      "run.cancelled",
    ]) {
      source.addEventListener(eventType, receive);
    }

    source.onerror = () => {
      if (settled || source.readyState !== EventSource.CLOSED) return;
      void getGraphRunState(runId, options.signal)
        .then((state) => {
          if (state.status === "completed") finish("completed");
          else if (state.status === "cancelled") finish("cancelled");
          else if (state.status === "failed") {
            finish("failed", new Error(state.error || "中央调度器执行失败"));
          } else {
            finish("failed", new Error("Agent 事件流意外中断"));
          }
        })
        .catch((error: unknown) =>
          finish(
            "failed",
            error instanceof Error ? error : new Error("Agent 事件流意外中断"),
          ),
        );
    };

    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener("abort", abort, { once: true });
  });
}
