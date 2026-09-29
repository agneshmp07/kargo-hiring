/** In development the Python API runs separately (npm run api, port 8100); on Vercel,
 *  /api/* is served by the Python function in api/index.py (see vercel.json). */
const nextConfig = {
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8100/api/:path*" },
      { source: "/apply", destination: "http://127.0.0.1:8100/api/apply" },
      { source: "/privacy", destination: "http://127.0.0.1:8100/api/privacy" },
    ];
  },
};
export default nextConfig;
