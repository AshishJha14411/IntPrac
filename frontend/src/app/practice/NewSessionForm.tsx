"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { GlowCard } from "@/components/ui/card";
import { ErrorNote, Notice } from "@/components/ui/feedback";
import { Hint, Input, Label, Select, Textarea } from "@/components/ui/field";
import { Segmented } from "@/components/ui/segmented";
import { ApiError, api } from "@/lib/api";
import type { Seniority, SessionPlan } from "@/lib/types";

type JdResponse = { id: string; status: string; thin: boolean };
type PresignResponse = {
  resume_id: string;
  version_id: string;
  version: number;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_in: number;
  complete_url: string;
};
type VersionResponse = { id: string; status: string; failure_reason: string | null };
type ResumeQuality = {
  rating: "strong" | "workable" | "sparse";
  competencies_found: number;
  items_found: number;
  suggestions: string[];
};
type ProfileResponse = { quality?: ResumeQuality };

/** Also the API's `mode`, so there is nothing to map and nothing to get wrong. */
type Source = "jd" | "resume" | "combined";

const NEEDS_JD: ReadonlySet<Source> = new Set<Source>(["jd", "combined"]);
const NEEDS_RESUME: ReadonlySet<Source> = new Set<Source>(["resume", "combined"]);

const SOURCES = [
  { value: "jd" as const, label: "A job description" },
  { value: "resume" as const, label: "My resume" },
  { value: "combined" as const, label: "Both" },
];

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const ACCEPTED: Record<string, string> = { "application/pdf": ".pdf", [DOCX]: ".docx" };
const MAX_BYTES = 10 * 1024 * 1024; // FR-R1, mirrored from the server

/**
 * Two ways in, and they choose the same thing: **which topics you get asked
 * about**. Neither ever reaches the grader (§1.2).
 *
 * The resume path is the one worth reading. The API signs an upload and the
 * browser PUTs **straight to object storage** — bytes never pass through the
 * application server (FR-R2), which is why a 10 MB file costs the API nothing.
 * Parsing is then asynchronous, so the UI polls a status rather than holding a
 * request open behind a worker.
 */
export function NewSessionForm() {
  const router = useRouter();
  const [source, setSource] = useState<Source>("jd");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [seniority, setSeniority] = useState<Seniority>("mid");
  const [minutes, setMinutes] = useState(20);
  const [status, setStatus] = useState<string | null>(null);
  // Shown after parsing, before planning. The interview will be full-length
  // either way -- this is so a candidate can improve the document rather than
  // wonder why the questions drifted away from their own experience.
  const [quality, setQuality] = useState<ResumeQuality | null>(null);

  /** Poll a status endpoint until it settles. Parsing is off the request path. */
  async function waitForParse(versionId: string): Promise<VersionResponse> {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const version = await api<VersionResponse>(`/resumes/versions/${versionId}`);
      if (["ready", "failed", "quarantined"].includes(version.status)) return version;
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
    throw new Error("Parsing is taking longer than expected. Try again in a moment.");
  }

  /** Submit the JD and wait for the worker to have a version to read. */
  async function submitJd(): Promise<string> {
    setStatus("Reading the job description…");
    const jd = await api<JdResponse>("/jds", {
      method: "POST",
      body: { title: title || "Untitled role", text },
    });

    // Parsing is asynchronous by design (FR-R3/J2): the UI polls rather
    // than blocking on a worker.
    setStatus("Choosing topics…");
    for (let attempt = 0; attempt < 30; attempt += 1) {
      try {
        await api(`/jds/versions/${jd.id}`);
        break;
      } catch (error) {
        if ((error as ApiError).status !== 404) throw error;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    return jd.id;
  }

  /** Presign, upload straight to storage, wait for parsing. */
  async function uploadResume(): Promise<string> {
    if (!file) throw new Error("Choose a resume file first.");

    setStatus("Asking for an upload link…");
      const presigned = await api<PresignResponse>("/resumes/presign", {
        method: "POST",
        body: {
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
          label: title || "My resume",
        },
      });

      setStatus("Uploading straight to storage…");
      // Deliberately `fetch`, not our `api()` helper: this request does not go
      // to our API at all, and attaching credentials to a third-party signed
      // URL would both break the signature and leak a cookie.
      const upload = await fetch(presigned.upload_url, {
        method: presigned.method,
        headers: { "Content-Type": file.type },
        body: file,
      });
      if (!upload.ok) {
        throw new Error(
          `Upload failed (${upload.status}). If this keeps happening the storage bucket is ` +
            "probably missing its CORS rule.",
        );
      }

      setStatus("Reading your resume…");
      await api(`/resumes/versions/${presigned.version_id}/complete`, { method: "POST" });
      const version = await waitForParse(presigned.version_id);
      if (version.status === "quarantined") {
        throw new Error(
          "That file looked like it was trying to instruct the system rather than describe " +
            "you, so it was quarantined. Nothing from it will be used.",
        );
      }
      if (version.status !== "ready") {
        throw new Error(
          version.failure_reason ??
            "That file could not be read. A text-based PDF or a DOCX works best — a scan of a " +
              "printout has no text in it to extract.",
        );
      }

    const profile = await api<ProfileResponse>(
      `/resumes/versions/${presigned.version_id}/profile`,
    ).catch(() => null);
    if (profile?.quality) setQuality(profile.quality);

    return presigned.version_id;
  }

  const start = useMutation({
    mutationFn: async (): Promise<SessionPlan> => {
      // The JD first in combined mode: it is the cheap one, and failing on a
      // 40-character paste before a 10 MB upload is the kinder order.
      const jdVersionId = NEEDS_JD.has(source) ? await submitJd() : undefined;
      const resumeVersionId = NEEDS_RESUME.has(source) ? await uploadResume() : undefined;

      setStatus("Building your interview plan…");
      return api<SessionPlan>("/sessions", {
        method: "POST",
        body: {
          // `source` *is* the mode -- see the type.
          mode: source,
          seniority,
          purpose: "practice",
          target_minutes: minutes,
          jd_version_id: jdVersionId,
          resume_version_id: resumeVersionId,
        },
      });
    },
    onSuccess: (plan) => router.push(`/interview/${plan.session.id}`),
    onError: () => setStatus(null),
  });

  const error = start.error as ApiError | null;
  // Every document the chosen mode needs, and nothing it doesn't. The server
  // enforces the same rule (`sessions.py` rejects a combined session missing
  // either); this is the faster, kinder no.
  const ready =
    (!NEEDS_JD.has(source) || text.length >= 40) &&
    (!NEEDS_RESUME.has(source) || (!!file && !fileError));

  function chooseFile(chosen: File | null) {
    setFileError(null);
    setFile(chosen);
    if (!chosen) return;
    // Checked here as well as on the server. Not a security control — the
    // server's is that — just a faster, kinder no than a round trip.
    if (!ACCEPTED[chosen.type]) {
      setFileError("PDF or DOCX only. Export from your editor rather than printing to an image.");
      setFile(null);
      return;
    }
    if (chosen.size > MAX_BYTES) {
      setFileError(`That file is ${(chosen.size / 1e6).toFixed(1)} MB. The limit is 10 MB.`);
      setFile(null);
    }
  }

  return (
    <GlowCard>
      <form
        className="space-y-6 p-6 sm:p-8"
        onSubmit={(event) => {
          event.preventDefault();
          start.mutate();
        }}
      >
        <div>
          <p className="mb-3 text-sm font-medium text-ink">What should choose the topics?</p>
          <Segmented
            options={SOURCES}
            value={source}
            onChange={setSource}
            ariaLabel="What should choose the topics?"
          />
        </div>

        {source === "combined" && (
          <Notice tone="accent" className="text-[0.8125rem]">
            With both, the questions come from the{" "}
            <strong className="font-semibold text-ink">overlap</strong> — what the role asks for
            and you have actually done. Where the role wants something your resume doesn&rsquo;t
            evidence, you&rsquo;ll be asked whether you could get there, not marked down for not
            being there already.
          </Notice>
        )}

        {error && (
          <ErrorNote role="alert">
            {error.code === "authentication-required" ? (
              <>
                You need to{" "}
                <a href="/login" className="font-semibold underline underline-offset-4">
                  sign in
                </a>{" "}
                first.
              </>
            ) : (
              error.message
            )}
          </ErrorNote>
        )}

        <div>
          <Label htmlFor="title">
            {NEEDS_JD.has(source) ? "Role title" : "Label for this resume"}
          </Label>
          <Input
            id="title"
            value={title}
            placeholder={NEEDS_JD.has(source) ? "Senior Backend Engineer" : "My resume"}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        {NEEDS_JD.has(source) && (
          <div>
            <Label htmlFor="jd">Job description</Label>
            <Textarea
              id="jd"
              required
              minLength={40}
              value={text}
              placeholder="Paste the full job description here…"
              onChange={(event) => setText(event.target.value)}
              aria-describedby="jd-help"
            />
            <Hint id="jd-help">
              The more specific the requirements, the better the topic selection. A vague JD
              produces a vague interview, and we&rsquo;ll tell you if that happens.
            </Hint>
          </div>
        )}

        {NEEDS_RESUME.has(source) && (
          <div>
            <Label htmlFor="resume">Your resume</Label>
            <Input
              id="resume"
              type="file"
              accept={Object.values(ACCEPTED).join(",")}
              onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              aria-describedby="resume-help"
            />
            {fileError && (
              <ErrorNote role="alert" className="mt-2 text-xs">
                {fileError}
              </ErrorNote>
            )}
            <Hint id="resume-help">
              PDF or DOCX, up to 10 MB. It goes{" "}
              <strong className="font-medium text-ink">straight to storage</strong> — the API only
              signs the link and never sees the file. What it extracts decides which topics you get
              asked about; it is then discarded, and nothing that grades you ever reads it.
            </Hint>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="seniority">Level</Label>
            <Select
              id="seniority"
              value={seniority}
              onChange={(event) => setSeniority(event.target.value as Seniority)}
              aria-describedby="seniority-help"
            >
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="minutes">Target length</Label>
            <Select
              id="minutes"
              value={minutes}
              onChange={(event) => setMinutes(Number(event.target.value))}
            >
              <option value={10}>10 minutes</option>
              <option value={20}>20 minutes</option>
              <option value={30}>30 minutes</option>
              <option value={45}>45 minutes</option>
            </Select>
          </div>
        </div>
        <Hint id="seniority-help" className="-mt-3">
          The same topic at a different level is graded against a different standard, so pick the
          level you&rsquo;re actually interviewing at. It is never inferred from your documents.
        </Hint>

        <div className="border-t border-line-soft pt-6">
          <Button type="submit" size="lg" disabled={start.isPending || !ready} className="w-full">
            {start.isPending ? (status ?? "Working…") : "Build my interview"}
          </Button>

          {start.isPending && status && (
            <p
              className="mt-3 flex items-center justify-center gap-2 text-xs text-muted"
              role="status"
              aria-live="polite"
            >
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent-soft"
              />
              {status}
            </p>
          )}
        </div>

        {quality && quality.rating !== "strong" && (
          <Notice role="status" className="text-[0.8125rem]">
            <strong className="font-semibold text-ink">
              Your resume yielded {quality.competencies_found} technical topic
              {quality.competencies_found === 1 ? "" : "s"}.
            </strong>{" "}
            The interview will still be full length — we fill the rest from related topics — but
            the more your resume evidences, the more of it is about{" "}
            <em className="text-ink/90">your</em> work.
            <ul className="mt-2.5 space-y-1.5">
              {quality.suggestions.map((suggestion, index) => (
                <li key={index} className="flex gap-2 text-muted">
                  <span aria-hidden="true" className="text-accent-soft">
                    →
                  </span>
                  {suggestion}
                </li>
              ))}
            </ul>
          </Notice>
        )}
      </form>
    </GlowCard>
  );
}
