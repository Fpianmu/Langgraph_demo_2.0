import { agentBackendUrl } from "@/lib/backend-url";

export async function POST(request: Request) {
  try {
    const upstream = await fetch(agentBackendUrl("/api/onboarding/assessments"), {
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
      { error: "无法创建入门测评", code: "ONBOARDING_UNAVAILABLE" },
      { status: 502 },
    );
  }
}
