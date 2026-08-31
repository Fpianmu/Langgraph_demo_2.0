import type { AgentRequest } from "@/lib/agent-contract";
import { agentBackendUrl } from "@/lib/backend-url";

function validRequest(value: unknown): value is AgentRequest {
  if (!value || typeof value !== "object") return false;
  const request = value as Partial<AgentRequest>;
  return (
    request.api_version === "v2" &&
    typeof request.request_id === "string" &&
    typeof request.user_id === "string" &&
    typeof request.course_id === "string" &&
    typeof request.raw_prompt === "string" &&
    ["qa", "quiz", "lecture", "practice", "feedback", "next_step"].includes(
      String(request.content_type),
    ) &&
    !!request.latest_scores &&
    !!request.learner_profile
  );
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { error: "请求体不是合法 JSON", code: "INVALID_JSON" },
      { status: 400 },
    );
  }

  if (!validRequest(body)) {
    return Response.json(
      { error: "请求字段不符合 LangGraph Demo 2.0 契约", code: "INVALID_REQUEST" },
      { status: 400 },
    );
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5 * 60_000);

  try {
    const created = await fetch(agentBackendUrl("/api/graph/runs"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const creation = (await created.json()) as { run_id?: string; detail?: string };
    if (!created.ok || !creation.run_id) {
      return Response.json(
        { error: creation.detail || "第二版中央调度器未创建任务" },
        { status: created.status },
      );
    }

    for (;;) {
      const resultResponse = await fetch(
        agentBackendUrl(`/api/graph/runs/${encodeURIComponent(creation.run_id)}/result`),
        { cache: "no-store", signal: controller.signal },
      );
      if (resultResponse.status === 202) {
        await new Promise((resolve) => setTimeout(resolve, 200));
        continue;
      }
      const resultBody = (await resultResponse.json()) as Record<string, unknown>;
      if (!resultResponse.ok) {
        return Response.json(
          { error: resultBody.detail || "中央调度器执行失败" },
          { status: resultResponse.status },
        );
      }
      const result =
        resultBody.result && typeof resultBody.result === "object"
          ? (resultBody.result as Record<string, unknown>)
          : resultBody;
      return Response.json(
        { ...result, api_version: "v2", request_id: body.request_id },
        { headers: { "X-Agent-Mode": "v2" } },
      );
    }
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AbortError"
        ? "多 Agent 服务响应超时"
        : "无法连接多 Agent 中央调度器";
    return Response.json(
      {
        error: message,
        code: "AGENT_UNAVAILABLE",
        hint: "请检查 AGENT_API_BASE_URL 和 LangGraph Demo 2.0 服务状态",
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}
