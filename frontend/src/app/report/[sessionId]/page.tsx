import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ErrorNote } from "@/components/ui/feedback";
import { PageHeader, Shell } from "@/components/ui/shell";
import { ApiError, INTERNAL_API_BASE, api } from "@/lib/api";
import { ReportBody } from "./ReportBody";
import type { SessionReport } from "@/lib/types";
import { ClientReport } from "./ClientReport";

export const metadata: Metadata = {
  title: "Your report",
  // A candidate's report is not for search engines.
  robots: { index: false, follow: false },
};

/**
 * The report is a **Server Component**: it is a read page with no interactive
 * state, so rendering it on the server means no client-side fetch waterfall
 * and no loading spinner for the thing the user actually came for.
 */
export default async function ReportPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  const cookieHeader = (await cookies()).toString();

  let report: SessionReport;
  try {
    report = await api<SessionReport>(`/sessions/${sessionId}/report`, {
      cookie: cookieHeader,
      base: INTERNAL_API_BASE,
    });
  } catch (error) {
    const problem = error as ApiError;
    // G-015: on a split-domain deployment the auth cookie belongs to the API
    // domain, so it never reaches this server and there is nothing to forward.
    // The *browser* has it, so hand the fetch to the client rather than
    // telling a signed-in user to sign in.
    if (problem.status === 401 || problem.code === "authentication-required") {
      return <ClientReport sessionId={sessionId} />;
    }
    return (
      <Shell>
        <PageHeader title="Report unavailable" />
        <ErrorNote role="alert">{problem.message}</ErrorNote>
      </Shell>
    );
  }

  return <ReportBody report={report} />;
}
