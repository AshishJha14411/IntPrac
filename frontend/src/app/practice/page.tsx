import type { Metadata } from "next";
import { PageHeader, Shell } from "@/components/ui/shell";
import { NewSessionForm } from "./NewSessionForm";

export const metadata: Metadata = { title: "Start a session" };

export default function PracticePage() {
  return (
    <Shell>
      <PageHeader
        eyebrow="New session"
        title="Start a practice session"
        lede={
          <>
            Paste a job description, or upload your resume. Either one chooses{" "}
            <strong className="font-medium text-ink">which topics you get asked about</strong> —
            and then it is discarded. Nothing that grades your answers ever sees it, so a
            flattering resume cannot buy you a better score.
          </>
        }
      />
      <NewSessionForm />
    </Shell>
  );
}
