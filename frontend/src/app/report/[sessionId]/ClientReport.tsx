"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import type { SessionReport } from "@/lib/types";

/**
 * The report, fetched from the browser instead of the server.
 *
 * G-015. The page is a Server Component, which means the *frontend server*
 * calls the API and forwards whatever cookie arrived with the page request.
 * On a split-domain deployment — `app.example.com` plus `api.example.com` with
 * `SameSite=None` — the auth cookie belongs to the API domain and is never
 * sent to the frontend domain at all. So the frontend server has no cookie to
 * forward, and `/report/{id}` renders "sign in" forever, while every
 * browser-side call on the same deployment works fine. A confusing failure:
 * one page broken, everything else healthy.
 *
 * The browser *does* hold that cookie and will send it to the API directly
 * (credentialed CORS), so the fallback is simply to ask from here.
 *
 * Deliberately a fallback and not the default: server rendering is the right
 * choice for a read page with no interactive state, and same-domain
 * deployments — the recommended shape — keep it. This only runs when the
 * server render came back unauthenticated.
 */
export function ClientReport({
  sessionId,
  children,
}: {
  sessionId: string;
  children: (report: SessionReport) => React.ReactNode;
}) {
  const report = useQuery({
    queryKey: ["report", sessionId],
    queryFn: () => api<SessionReport>(`/sessions/${sessionId}/report`),
    retry: false,
    // Grading finishes in the background, so keep asking while anything is
    // outstanding — and stop the moment nothing is, which is the fix from
    // G-008 seen from the client side.
    refetchInterval: (query) =>
      (query.state.data?.pending_questions ?? 0) > 0 ? 4000 : false,
  });

  if (report.isLoading) {
    return (
      <div className="shell">
        <p className="muted">Loading your report…</p>
      </div>
    );
  }

  // `isError` alone does not narrow `data`, and a genuinely absent report is
  // the same dead end as an error — so both are handled together.
  if (report.isError || !report.data) {
    const problem = report.error as ApiError | null;
    return (
      <div className="shell">
        <h1>Report unavailable</h1>
        <p className="error">{problem?.message ?? "That report could not be loaded."}</p>
        {problem?.status === 401 && <a href="/login">Sign in</a>}
      </div>
    );
  }

  return <>{children(report.data)}</>;
}
