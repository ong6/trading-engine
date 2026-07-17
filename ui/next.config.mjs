/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy every /api/* call to the local FastAPI backend so the browser only
  // ever talks to :3000 (no CORS). Server-side fetches also go through this.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
