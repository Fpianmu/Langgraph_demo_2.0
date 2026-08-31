import { agentBackendUrl } from "@/lib/backend-url";

export async function GET() {
  try {
    const upstream = await fetch(agentBackendUrl("/api/agent/health"), { cache: "no-store" });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { status: "unavailable", error: "无法连接多 Agent 中央调度器" },
      { status: 502 },
    );
  }
}
