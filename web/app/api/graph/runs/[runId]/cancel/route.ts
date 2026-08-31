import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ runId: string }> };

export async function POST(_request: Request, context: RouteContext) {
  const { runId } = await context.params;
  try {
    const upstream = await fetch(
      agentBackendUrl(`/api/graph/runs/${encodeURIComponent(runId)}/cancel`),
      { method: "POST", cache: "no-store" },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法取消 Agent 任务", code: "RUN_CANCEL_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
