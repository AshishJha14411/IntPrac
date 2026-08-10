import type { Metadata } from "next";
import { NewSessionForm } from "./NewSessionForm";

export const metadata: Metadata = { title: "Start a session" };

export default function PracticePage() {
  return (
    <div className="shell">
      <h1>Start a practice session</h1>
      <p className="muted">
        Paste a job description, or upload your resume. Either one chooses{" "}
        <strong>which topics you get asked about</strong> — and then it is discarded. Nothing
        that grades your answers ever sees it, so a flattering resume cannot buy you a better
        score.
      </p>
      <NewSessionForm />
    </div>
  );
}
