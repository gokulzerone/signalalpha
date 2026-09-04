import type { NextConfig } from "next";

// `output: "standalone"` produces the self-contained server the container image copies, but
// it makes `next start` exit immediately, which breaks running the app locally. Build it only
// when the Dockerfile asks for it.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(process.env.NEXT_STANDALONE === "1" ? { output: "standalone" as const } : {}),
};

export default nextConfig;
