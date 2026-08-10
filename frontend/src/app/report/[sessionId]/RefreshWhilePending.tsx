"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * A tiny client island inside an otherwise server-rendered page.
 *
 * Grading is asynchronous, so a report opened immediately after a session may
 * still be filling in. Rather than turn the whole page into a client component
 * to poll, this refreshes the server render until nothing is pending.
 */
export function RefreshWhilePending({ intervalMs = 4000 }: { intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [router, intervalMs]);
  return null;
}
