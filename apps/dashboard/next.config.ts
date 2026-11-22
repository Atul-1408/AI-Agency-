import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Enabled during Docker container builds for minimal production images
  output: process.env.BUILD_STANDALONE === "true" ? "standalone" : undefined,
  // Point Turbopack to the monorepo root so it can find shared packages
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
