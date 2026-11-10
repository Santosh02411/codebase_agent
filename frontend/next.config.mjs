/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export: `scripts/build_frontend.sh` copies the result into app/webapp, and FastAPI serves it at http://localhost:8000
  // (same origin as the API, so no CORS and no second server). `npm run dev` still works for frontend development on port 3000.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};
export default nextConfig;
