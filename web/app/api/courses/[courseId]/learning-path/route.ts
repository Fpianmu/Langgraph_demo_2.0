import { agentBackendUrl } from "@/lib/backend-url";

type RouteContext = { params: Promise<{ courseId: string }> };

export async function GET(request: Request, context: RouteContext) {
  const { courseId } = await context.params;
  const requestUrl = new URL(request.url);
  const pathId = requestUrl.searchParams.get("path_id")?.trim();
  const query = pathId ? `?path_id=${encodeURIComponent(pathId)}` : "";

  try {
    const upstream = await fetch(
      agentBackendUrl(
        `/api/courses/${encodeURIComponent(courseId)}/learning-path${query}`,
      ),
      { cache: "no-store" },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return Response.json(
      { error: "无法读取后端学习路径目录", code: "LEARNING_PATH_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
