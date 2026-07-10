import type { NextConfig } from "next";

// In docker compose this is http://backend:8000; for local dev the default
// hits a locally running uvicorn.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/outputs/:path*", destination: `${backendUrl}/outputs/:path*` },
    ];
  },
};

export default nextConfig;
