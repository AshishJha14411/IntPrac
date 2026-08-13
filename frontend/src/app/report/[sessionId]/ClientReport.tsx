"use client";

import { useQuery } from "@tanstack/react-query";
import { LinkButton } from "@/components/ui/button";
import { ErrorNote } from "@/components/ui/feedback";
import { PageHeader, Shell } from "@/components/ui/shell";
import { ApiError, api } from "@/lib/api";
import type { SessionReport } from "@/lib/types";
import { ReportBody } from "./ReportBody";

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
 * ⚠ This takes `sessionId` and nothing else, and renders `ReportBody` by
 * importing it. It used to accept the body as a render prop — a function —
 * which a Server Component cannot pass to a Client Component: React has to
 * serialise the props and a closure has no serialisation, so it substituted
 * an Error. The fallback for the 401 became the cause of a "Something went
 * wrong" page, in production only, because same-origin dev forwards the
 * cookie and never reaches this branch.
 *
 * Deliberately a fallback and not the default: server rendering is the right
 * choice for a read page with no interactive state, and same-domain
 * deployments — the recommended shape — keep it. This only runs when the
 * server render came back unauthenticated.
 */
export function ClientReport({ sessionId }: { sessionId: string }) {
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
      <Shell width="wide">
        <p className="animate-pulse text-sm text-muted">Loading your report…</p>
      </Shell>
    );
  }

  // `isError` alone does not narrow `data`, and a genuinely absent report is
  // the same dead end as an error — so both are handled together.
  if (report.isError || !report.data) {
    const problem = report.error as ApiError | null;
    return (
      <Shell>
        <PageHeader title="Report unavailable" />
        <ErrorNote role="alert">
          {problem?.message ?? "That report could not be loaded."}
        </ErrorNote>
        {problem?.status === 401 && (
          <LinkButton href="/login" className="mt-5">
            Sign in
          </LinkButton>
        )}
      </Shell>
    );
  }

  return <ReportBody report={report.data} />;
}
