import { resolveApiOrigin } from "./api-origin.mjs";

const apiOrigin = resolveApiOrigin();

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy every /api/* call to the local FastAPI backend so the browser only
  // ever talks to the UI origin (no CORS). The same validated origin is used
  // by server-rendered fetches.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
