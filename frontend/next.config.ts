import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The API is a separate origin. Types come from its OpenAPI schema
  // (`npm run gen:api`), so contract drift is a compile error, not a
  // runtime `undefined` (Appendix D.6).
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080",
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default config;
