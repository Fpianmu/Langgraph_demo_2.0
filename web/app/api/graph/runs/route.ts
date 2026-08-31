import { agentBackendUrl } from "@/lib/backend-url";

export async function POST(request: Request) {
  try {
    const upstream = await fetch(agentBackendUrl("/api/graph/runs"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法连接第二版多 Agent 中央调度器", code: "AGENT_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
