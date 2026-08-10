import type { Metadata } from "next";
import { InterviewRoom } from "./InterviewRoom";

export const metadata: Metadata = { title: "Interview", robots: { index: false } };

export default async function InterviewPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  // The room is a client island: everything about it is interactive, and it
  // has to survive a refresh mid-session (FR-S8), so it owns its own state.
  return <InterviewRoom sessionId={sessionId} />;
}
