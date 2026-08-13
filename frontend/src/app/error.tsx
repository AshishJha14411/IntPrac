"use client";

import { Button } from "@/components/ui/button";
import { Aurora, GridGround } from "@/components/ui/backgrounds";
import { PageHeader, Shell } from "@/components/ui/shell";

/** App Router error boundary. Never leaks internals to the page. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="relative isolate">
      <Aurora className="h-[30rem]" />
      <GridGround className="h-[30rem]" />
      <Shell className="relative">
        <PageHeader
          eyebrow="Error"
          title="Something went wrong"
          lede="This has been logged. If you were part-way through an interview, your answers are safe — reopening the session picks up where you left off."
          actions={<Button onClick={reset}>Try again</Button>}
        />
        {error.digest && (
          <p className="font-mono text-xs text-faint">Reference: {error.digest}</p>
        )}
      </Shell>
    </div>
  );
}
