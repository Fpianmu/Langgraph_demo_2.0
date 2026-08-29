const DEFAULT_AGENT_BASE_URL = "http://127.0.0.1:8000";

export function agentBackendUrl(pathname: string): string {
  const configuredBase = process.env.AGENT_API_BASE_URL?.trim();
  if (configuredBase) {
    return new URL(pathname, `${configuredBase.replace(/\/$/, "")}/`).toString();
  }

  return new URL(pathname, `${DEFAULT_AGENT_BASE_URL}/`).toString();
}
