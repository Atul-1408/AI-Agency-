import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Point Turbopack to the monorepo root so it can find shared packages
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
