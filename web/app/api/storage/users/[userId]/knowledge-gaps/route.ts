import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ userId: string }> };

export async function GET(_request: Request, context: RouteContext) {
  const { userId } = await context.params;
  try {
    const upstream = await fetch(
      agentBackendUrl(
        `/api/storage/users/${encodeURIComponent(userId)}/knowledge-gaps`,
      ),
      { cache: "no-store" },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法读取后端知识漏洞记录", code: "KNOWLEDGE_GAPS_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
