import { agentBackendUrl } from "@/lib/backend-url";

const DEFAULT_PATH = "/agent/quiz/grade";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "请求体不是合法 JSON" }, { status: 400 });
  }
  const endpoint = process.env.QUIZ_GRADE_API_URL || agentBackendUrl(DEFAULT_PATH);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90_000);
  try {
    const upstream = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/json; charset=utf-8",
      },
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error && error.name === "AbortError"
            ? "主观题评分超时"
            : "无法连接中央调度器的主观题评分服务",
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}

