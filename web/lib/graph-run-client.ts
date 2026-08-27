"use client";

export type GraphRunEvent = {
  event_type: string;
  event_id: string;
  run_id: string;
  created_at?: string;
  agent_id?: string;
  agent_display_name?: string;
  node_id?: string;
  display_text?: string;
  detail?: string;
  from_agent?: string;
  to_agent?: string;
  message_type?: string;
  payload_refs?: Record<string, unknown>;
};

export type GraphRunHandle = {
  runId: string;
  done: Promise<void>;
  close: () => void;
};

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const message =
      data && typeof data === "object" && "detail" in data
        ? String((data as { detail?: unknown }).detail || "")
        : text || `HTTP ${response.status}`;
    throw new Error(message || `HTTP ${response.status}`);
  }
  return data as T;
}

export async function createGraphRun(payload: unknown): Promise<string> {
  const response = await fetch("/api/graph/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await parseJsonResponse<{ run_id?: string }>(response);
  if (!data.run_id) {
    throw new Error("图运行接口未返回 run_id");
  }
  return data.run_id;
}

export function streamGraphRunEvents(
  runId: string,
  onEvent: (event: GraphRunEvent) => void,
): GraphRunHandle {
  const source = new EventSource(`/api/graph/runs/${encodeURIComponent(runId)}/events`);
  let settled = false;

  const done = new Promise<void>((resolve, reject) => {
    const finish = () => {
      if (settled) return;
      settled = true;
      source.close();
      resolve();
    };
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      source.close();
      reject(error);
    };

    const handlers = [
      "run.started",
      "agent.activity",
      "agent.message",
      "agent.completed",
      "run.completed",
      "agent.failed",
      "run.failed",
    ] as const;

    const parseEvent = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as GraphRunEvent;
        onEvent(data);
        if (data.event_type === "run.completed" || data.event_type === "agent.completed") {
          finish();
        } else if (data.event_type === "run.failed" || data.event_type === "agent.failed") {
          fail(new Error(data.detail || "图运行失败"));
        }
      } catch (error) {
        fail(error instanceof Error ? error : new Error("无法解析图运行事件"));
      }
    };

    for (const type of handlers) {
      source.addEventListener(type, parseEvent as EventListener);
    }
  });

  return {
    runId,
    done,
    close() {
      if (settled) return;
      settled = true;
      source.close();
    },
  };
}
