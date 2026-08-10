"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
 * TanStack Query owns all server state.
 *
 * This is what deletes the whole useEffect/loading/error/cancelled bug family
 * (Appendix D.6): no manual fetch-in-effect, no stale-closure race, no
 * "component unmounted" warnings.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (failureCount, error) => {
              // Never retry a 4xx: the request was wrong, and repeating it
              // just makes the same mistake more times.
              const status = (error as { status?: number }).status;
              if (status && status >= 400 && status < 500) return false;
              return failureCount < 2;
            },
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
