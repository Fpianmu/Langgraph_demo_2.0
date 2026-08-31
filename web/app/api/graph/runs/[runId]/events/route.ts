import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ runId: string }> };

export async function GET(request: Request, context: RouteContext) {
  const { runId } = await context.params;
  const headers = new Headers({ Accept: "text/event-stream" });
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);

  try {
    const upstream = await fetch(
      agentBackendUrl(`/api/graph/runs/${encodeURIComponent(runId)}/events`),
      { headers, cache: "no-store", signal: request.signal },
    );
    if (!upstream.ok || !upstream.body) {
      return new Response(await upstream.text(), { status: upstream.status });
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json(
      { error: "无法监听 Agent 活动", code: "EVENT_STREAM_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
