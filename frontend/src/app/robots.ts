import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/"],
      // Candidate interviews and reports are private by default, and a
      // disallow rule is cheaper than discovering they were indexed.
      disallow: ["/interview/", "/report/", "/practice"],
    },
  };
}
