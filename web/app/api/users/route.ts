import { agentBackendUrl } from "@/lib/backend-url";

async function forward(init?: RequestInit) {
  try {
    const upstream = await fetch(agentBackendUrl("/api/users"), {
      ...init,
      cache: "no-store",
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法连接第二版后端用户服务", code: "USER_SERVICE_UNAVAILABLE" },
      { status: 502 },
    );
  }
}

export async function GET() {
  return forward();
}

export async function POST(request: Request) {
  return forward({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
}
