import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ runId: string }> };

export async function GET(_request: Request, context: RouteContext) {
  const { runId } = await context.params;
  try {
    const upstream = await fetch(
      agentBackendUrl(`/api/graph/runs/${encodeURIComponent(runId)}/result`),
      { cache: "no-store" },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法读取 Agent 任务结果", code: "RESULT_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
