import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ userId: string }> };

async function forward(userId: string, init?: RequestInit) {
  try {
    const upstream = await fetch(
      agentBackendUrl(`/api/frontend-state/${encodeURIComponent(userId)}`),
      { ...init, cache: "no-store" },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法连接后端 Memory 服务", code: "PROFILE_UNAVAILABLE" },
      { status: 502 },
    );
  }
}

export async function GET(_request: Request, context: RouteContext) {
  const { userId } = await context.params;
  return forward(userId);
}

export async function PUT(request: Request, context: RouteContext) {
  const { userId } = await context.params;
  return forward(userId, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
}
