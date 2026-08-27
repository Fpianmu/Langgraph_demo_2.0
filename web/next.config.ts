import type { NextConfig } from "next";

function resolveBackendOrigin(): string {
  const configuredBase = process.env.AGENT_API_BASE_URL?.trim();
  if (configuredBase) {
    return new URL(configuredBase.replace(/\/$/, "")).origin;
  }

  const configuredGenerateUrl = process.env.AGENT_API_URL?.trim();
  if (configuredGenerateUrl) {
    return new URL(configuredGenerateUrl).origin;
  }

  return "http://127.0.0.1:8000";
}

const nextConfig: NextConfig = {
  async rewrites() {
    const backendOrigin = resolveBackendOrigin();
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
