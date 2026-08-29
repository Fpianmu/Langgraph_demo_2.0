import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ userId: string }> };

export async function POST(request: Request, context: RouteContext) {
  const { userId } = await context.params;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "请求体不是合法 JSON" }, { status: 400 });
  }
  try {
    const upstream = await fetch(
      agentBackendUrl(`/api/storage/users/${encodeURIComponent(userId)}/quiz-evidence`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法同步 Quiz 能力证据", code: "QUIZ_EVIDENCE_SYNC_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
