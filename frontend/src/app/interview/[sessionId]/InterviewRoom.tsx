"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb, Mic, Square, Volume2, VolumeX } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, LinkButton } from "@/components/ui/button";
import { Card, GlowCard, GradientCard } from "@/components/ui/card";
import { Badge, ErrorNote, Meter, Notice } from "@/components/ui/feedback";
import { CheckField, Label, Textarea } from "@/components/ui/field";
import { Segmented } from "@/components/ui/segmented";
import { PageHeader, Shell } from "@/components/ui/shell";
import { useDictation } from "@/hooks/useDictation";
import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LOW_CONFIDENCE, type TranscriptSegment } from "@/lib/speech";
import type { AnswerResult, Hint, SessionPlan, Turn } from "@/lib/types";

type Mode = "voice" | "text";

const ANSWER_MODES = [
  { value: "voice" as const, label: "Speak" },
  { value: "text" as const, label: "Type" },
];

/**
 * The interview room.
 *
 * Responsibilities:
 *
 * 1. **The consent gate.** Nothing starts until every item is accepted, and
 *    the disclosure says plainly what is and is not scored (FR-S2).
 * 2. **Resumability.** On mount it asks the server what turn we're on, so a
 *    refresh or a dropped connection lands you back where you were (FR-S8).
 * 3. **Idempotent submission.** The key is minted once per attempt and reused
 *    across retries, so a resend can never double-record (FR-S8).
 * 4. **Voice, with text as a peer (FR-V).** Interviews are spoken, so speaking
 *    is the default. But grading only ever sees the transcript (FR-V5), so the
 *    two modes are not a fast path and a slow one — they are the same path with
 *    different keyboards. A candidate who cannot speak, will not be understood
 *    by a recogniser, or simply does not want to talk is not disadvantaged, and
 *    that is a property of the architecture rather than a promise in a policy.
 */
export function InterviewRoom({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [hints, setHints] = useState<Hint[]>([]);
  const [consent, setConsent] = useState({ ai: false, recording: false, retention: false });
  const [mode, setMode] = useState<Mode>("voice");
  const [muted, setMuted] = useState(false);
  const [onDevice, setOnDevice] = useState(false);
  const [mic, setMic] = useState<"unknown" | "granted" | "blocked">("unknown");
  const answerRef = useRef<HTMLTextAreaElement>(null);

  // Voice is the default, full stop. Which *engine* delivers it is the hook's
  // problem: the browser's own where it exists, an on-device model where it
  // doesn't. `onDevice` is the candidate forcing the second one to keep their
  // audio off a vendor's servers — their call, not ours.
  const speech = useDictation(onDevice ? "wasm" : undefined);
  const voice = useSpeechSynthesis();

  const plan = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api<SessionPlan>(`/sessions/${sessionId}`),
  });

  const status = plan.data?.session.status;
  const inProgress = status === "in_progress";

  // FR-S8: ask the server where we are rather than trusting local state.
  const turn = useQuery({
    queryKey: ["turn", sessionId],
    queryFn: () => api<Turn>(`/sessions/${sessionId}/turn`),
    enabled: inProgress,
  });

  const giveConsent = useMutation({
    mutationFn: () =>
      api(`/sessions/${sessionId}/consent`, {
        method: "POST",
        body: {
          accepts_ai_assessment: consent.ai,
          accepts_recording: consent.recording,
          accepts_retention: consent.retention,
        },
      }),
    onSuccess: () => start.mutate(),
  });

  const start = useMutation({
    mutationFn: () => api<Turn>(`/sessions/${sessionId}/start`, { method: "POST" }),
    onSuccess: (next) => {
      queryClient.setQueryData(["turn", sessionId], next);
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    },
  });

  /**
   * G-004: one key per *logical answer*, not per attempt.
   *
   * This was minted inside `mutationFn`, so every retry sent a different key —
   * and a key that changes is not an idempotency key, it is a random string.
   * The exact failure: the server commits, the response is lost, the UI shows
   * an error, you press submit again, and the second request looks like a
   * brand-new answer. It could append an extra turn, trigger a follow-up you
   * never earned, or advance the interview twice.
   *
   * Held in a ref rather than state because changing it must never re-render:
   * it is minted on first attempt, reused by every retry of that attempt, and
   * cleared only once the server has definitively accepted it.
   */
  const answerKey = useRef<string | null>(null);

  const submit = useMutation({
    mutationFn: (payload: {
      questionId: string;
      text: string;
      skipped: boolean;
      segments?: TranscriptSegment[];
      durationMs?: number;
    }) => {
      answerKey.current ??= newIdempotencyKey();
      return api<AnswerResult>(`/sessions/${sessionId}/answers`, {
        method: "POST",
        body: {
          question_id: payload.questionId,
          transcript: payload.text,
          skipped: payload.skipped,
          input_mode: mode === "voice" ? "speech" : "typed",
          // Only what was actually spoken. Sending segments for a typed answer
          // would put a timeline on something that never had one.
          // From the finalized result, not from state: the last segment may have
          // arrived after this render closed over `speech.segments`.
          segments: mode === "voice" && !payload.skipped ? (payload.segments ?? []) : [],
          duration_ms: mode === "voice" ? (payload.durationMs ?? null) : null,
          idempotency_key: answerKey.current,
        },
      });
    },
    onSuccess: (result) => {
      // Only now is the answer definitively recorded, so only now may the key
      // be retired. Clearing it on error instead would hand the next attempt a
      // fresh key and recreate the bug.
      answerKey.current = null;
      speech.reset();
      setHints([]);
      if (result.session_completed) {
        router.push(`/report/${sessionId}`);
        return;
      }
      if (result.next_turn) queryClient.setQueryData(["turn", sessionId], result.next_turn);
    },
  });

  const askHint = useMutation({
    mutationFn: (questionId: string) =>
      api<Hint>(`/sessions/${sessionId}/hints`, {
        method: "POST",
        body: { question_id: questionId, trigger: "requested" },
      }),
    onSuccess: (hint) => setHints((current) => [...current, hint]),
  });

  /**
   * Ask for the microphone before the interview rather than during it.
   *
   * This is what `device_check` in the session state machine is for: a
   * permission prompt that lands on top of question one costs the candidate
   * the start of their answer.
   */
  const checkMicrophone = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Release it immediately. We only wanted the permission, and a hot mic
      // sitting open through the consent screen is indefensible.
      stream.getTracks().forEach((track) => track.stop());
      setMic("granted");
    } catch {
      setMic("blocked");
    }
  }, []);

  const currentQuestionId = turn.data?.question_id;
  const currentPrompt = turn.data
    ? turn.data.is_followup && turn.data.followup_prompt
      ? turn.data.followup_prompt
      : turn.data.prompt
    : null;

  // Focus management: each new question moves focus to the answer box so a
  // keyboard or screen-reader user isn't hunting for it (NFR-A).
  useEffect(() => {
    if (currentQuestionId) answerRef.current?.focus();
  }, [currentQuestionId]);

  // FR-V1: the interviewer asks out loud. Only in voice mode, only unmuted,
  // and never on the consent screen — a page that starts talking by itself
  // talks over a screen reader.
  //
  // G-007: depends on `speak`/`cancel`, never on the whole `voice` object.
  // `useSpeechSynthesis` returns a fresh object whenever `speaking` flips, so
  // depending on it meant: speak → speaking=true → new object → effect reruns
  // → cleanup cancels → speaks again. The question stuttered and restarted,
  // and "Stop reading" was unwinnable because stopping flipped `speaking` and
  // retriggered the effect.
  //
  // The cleanup also no longer cancels. It used to run on every re-render that
  // touched a dependency, cutting off speech that was legitimately playing;
  // `speak()` already cancels the previous utterance, and leaving the room is
  // handled by the hook's own unmount cleanup.
  const { speak, cancel: cancelSpeech } = voice;
  useEffect(() => {
    if (mode !== "voice" || muted || !currentPrompt || !inProgress) return;
    speak(currentPrompt);
  }, [currentPrompt, mode, muted, inProgress, speak]);

  if (plan.isLoading) {
    return (
      <Shell>
        <p className="animate-pulse text-sm text-muted">Loading…</p>
      </Shell>
    );
  }

  if (plan.isError) {
    const error = plan.error as ApiError;
    return (
      <Shell>
        <ErrorNote role="alert">
          {error.code === "authentication-required"
            ? "Please sign in to continue."
            : error.message}
        </ErrorNote>
      </Shell>
    );
  }

  // ── consent gate ────────────────────────────────────────────────────────
  if (status === "consent_pending" || status === "planned" || status === "device_check") {
    const allAccepted = consent.ai && consent.recording && consent.retention;
    return (
      <Shell>
        <PageHeader eyebrow="Before you start" title="What this session does with your words" />

        <GradientCard className="mb-6">
          <div className="space-y-4 p-6 sm:p-7">
            <Disclosure heading="An AI conducts and assesses this interview.">
              A human is not watching it live.
            </Disclosure>
            <Disclosure heading="What is scored:">
              Whether your explanation of the mechanism is correct, how deep it goes, whether you
              ground it in specifics, and whether it is followable.
            </Disclosure>
            <Disclosure heading="What is never scored:">
              Your accent, fluency, grammar, speaking speed, confidence, or anything inferred from
              your face or voice. Terminology carries zero weight — the right idea in the wrong
              words is full credit.
            </Disclosure>
            <Disclosure heading="What is recorded:">
              The transcript, whether you type it or speak it. This app stores and uploads{" "}
              <strong className="font-semibold text-ink">no audio and no video</strong>.
              {speech.engine === "native" ? (
                <>
                  {" "}
                  Speaking uses your browser&rsquo;s built-in recognition, and some browsers —
                  Chrome and Edge among them — send that audio to the browser vendor to transcribe
                  it. Keeping it on this device, or typing, both avoid that and are scored
                  identically.
                </>
              ) : (
                <>
                  {" "}
                  Speaking runs a speech model{" "}
                  <strong className="font-semibold text-ink">on this device</strong>, so your audio
                  does not leave your machine at all.
                </>
              )}
            </Disclosure>

            <p className="text-xs leading-relaxed text-faint">
              Kept for up to <strong className="font-medium text-muted">6 months</strong>, then
              deleted automatically &mdash; transcripts included, not just files. You can delete
              this session, or your whole account, at any time from{" "}
              <a href="/dashboard" className="text-accent-soft underline underline-offset-4">
                My interviews
              </a>
              .
            </p>

            <fieldset className="space-y-2.5 border-0 p-0">
              <legend className="sr-only">Consent</legend>
              {(
                [
                  ["ai", "I understand an AI conducts and assesses this interview."],
                  ["recording", "I consent to my transcript being recorded."],
                  ["retention", "I understand the retention period and how to delete my data."],
                ] as const
              ).map(([key, label]) => (
                <CheckField
                  key={key}
                  checked={consent[key]}
                  onChange={(next) => setConsent((current) => ({ ...current, [key]: next }))}
                >
                  {label}
                </CheckField>
              ))}
            </fieldset>

            <Button
              size="lg"
              className="w-full"
              disabled={!allAccepted || giveConsent.isPending || start.isPending}
              onClick={() => giveConsent.mutate()}
            >
              {giveConsent.isPending || start.isPending ? "Starting…" : "I agree — start"}
            </Button>
            {!allAccepted && (
              <p className="text-center text-xs text-faint">
                All three are required. Without consent there is no session — that is deliberate.
              </p>
            )}
          </div>
        </GradientCard>

        <h2 className="mt-10 mb-4 text-xl font-semibold tracking-tight text-ink">
          How you&rsquo;ll answer
        </h2>
        <Card className="space-y-5 p-6">
          <p className="text-sm leading-relaxed text-muted">
            Answers are <strong className="font-medium text-ink">spoken by default</strong>, the
            way an interview actually works. You can switch to typing at any point during the
            session, including mid-answer, and it is scored exactly the same — only the transcript
            is graded.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" size="sm" onClick={checkMicrophone}>
              <Mic aria-hidden="true" className="h-3.5 w-3.5" />
              Check my microphone
            </Button>
            <span
              className={cn(
                "text-xs",
                mic === "granted" && "text-covered",
                mic === "blocked" && "text-missed",
                mic === "unknown" && "text-muted",
              )}
              role="status"
            >
              {mic === "granted" && "✓ Microphone ready."}
              {mic === "blocked" && "Blocked — allow it in your browser, or just type instead."}
              {mic === "unknown" && "Worth doing now, so the prompt doesn't interrupt you."}
            </span>
          </div>
          <CheckField
            checked={onDevice || speech.engine === "wasm"}
            disabled={speech.engine === "wasm" && !onDevice}
            onChange={setOnDevice}
          >
            <span className="font-medium text-ink">Keep my voice on this device.</span>{" "}
            <span className="text-muted">
              {speech.engine === "wasm" && !onDevice
                ? "Your browser has no built-in recognition, so this is the only option — and it is the more private one."
                : "Runs the speech model locally instead of your browser's cloud one. One-off ~40 MB download, then nothing leaves your machine."}
            </span>
          </CheckField>
        </Card>

        <h2 className="mt-10 mb-2 text-xl font-semibold tracking-tight text-ink">Your plan</h2>
        <p className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted">
          <Badge>{plan.data?.questions.length} questions</Badge>
          <Badge>{plan.data?.session.seniority} level</Badge>
          <Badge>{plan.data?.session.target_minutes} minutes</Badge>
        </p>
        <Card className="divide-y divide-line-soft">
          {plan.data?.questions.map((question, index) => (
            <div key={question.id} className="flex items-center gap-3 px-5 py-3">
              <span className="w-5 shrink-0 font-mono text-xs text-faint">{index + 1}</span>
              <code className="font-mono text-xs text-accent-soft">{question.competency_id}</code>
              <span className="truncate text-xs text-muted">
                {question.competency_id.replace(/-/g, " ")}
              </span>
            </div>
          ))}
        </Card>
      </Shell>
    );
  }

  if (status && ["completed", "graded", "published", "reviewed"].includes(status)) {
    return (
      <Shell>
        <PageHeader
          title="Interview complete"
          lede="Your report is being prepared."
          actions={<LinkButton href={`/report/${sessionId}`}>Open my report</LinkButton>}
        />
      </Shell>
    );
  }

  // ── turn loop ───────────────────────────────────────────────────────────
  const current = turn.data;
  if (!current) {
    return (
      <Shell>
        <p className="animate-pulse text-sm text-muted">Loading the next question…</p>
      </Shell>
    );
  }

  const progress = ((current.ordinal + 1) / Math.max(1, current.total)) * 100;
  const submitError = submit.error as ApiError | null;
  const uncertain = speech.segments.filter(
    (segment) => segment.confidence !== null && segment.confidence < LOW_CONFIDENCE,
  );
  const hasAnswer = speech.text.trim().length > 0;

  return (
    <Shell>
      <div className="mb-2 flex items-baseline justify-between gap-3 text-xs text-muted">
        <span className="font-medium text-ink">
          Question {current.ordinal + 1}{" "}
          <span className="font-normal text-faint">of {current.total}</span>
        </span>
        {/* An estimate, said as one. Nothing ends the session on time: this is
            practice, so every planned question gets asked however long it
            takes. A bare countdown would imply a deadline that does not
            exist. */}
        <span title="An estimate. Nothing cuts the session short — you'll get all the questions.">
          ~{current.remaining_minutes} min left (estimate)
        </span>
      </div>
      <Meter
        percent={progress}
        valueNow={current.ordinal + 1}
        valueMin={1}
        valueMax={current.total}
        ariaLabel="Interview progress"
        className="mb-8"
      />

      <GlowCard className="mb-5 p-6 sm:p-7">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="mono">{current.competency_id}</Badge>
          {current.is_followup && <Badge tone="accent">Follow-up</Badge>}
        </div>
        <p
          className="mt-4 text-lg leading-relaxed text-ink text-pretty sm:text-xl"
          aria-live="polite"
        >
          {currentPrompt}
        </p>
        {current.is_followup && (
          <p className="mt-3 text-xs text-faint">
            Follow-up on the same question — still the same topic, no new subject.
          </p>
        )}
        {voice.supported && (
          <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line-soft pt-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => (voice.speaking ? voice.cancel() : voice.speak(currentPrompt ?? ""))}
            >
              {voice.speaking ? (
                <VolumeX aria-hidden="true" className="h-3.5 w-3.5" />
              ) : (
                <Volume2 aria-hidden="true" className="h-3.5 w-3.5" />
              )}
              {voice.speaking ? "Stop reading" : "Read the question again"}
            </Button>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-line-strong bg-glass-3 accent-accent"
                checked={muted}
                onChange={(event) => setMuted(event.target.checked)}
              />
              <span>Don&rsquo;t read questions aloud</span>
            </label>
          </div>
        )}
      </GlowCard>

      {hints.map((hint, index) => (
        <Notice tone="accent" key={index} className="mb-3 text-[0.8125rem]" role="status">
          <span className="flex gap-2.5">
            <Lightbulb aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-partial" />
            <span>
              <strong className="font-semibold text-ink">Hint {index + 1}:</strong> {hint.text}
              <span className="mt-1.5 block text-xs text-muted">{hint.scoring_note}</span>
            </span>
          </span>
        </Notice>
      ))}

      {submitError && (
        <ErrorNote role="alert" className="mb-3">
          {submitError.message}
        </ErrorNote>
      )}
      {speech.error && (
        <ErrorNote role="alert" className="mb-3">
          {speech.error}
        </ErrorNote>
      )}

      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          // G-006: wait for the recogniser to hand over its last words before
          // sending. Both engines finalise asynchronously, so the previous
          // `stop(); submit(speech.text)` could send a transcript missing the
          // end of the answer — and the transcript is what gets graded.
          void (async () => {
            const final = await speech.finalize();
            submit.mutate({
              questionId: current.question_id,
              text: final.text,
              segments: final.segments,
              durationMs: final.durationMs,
              skipped: false,
            });
          })();
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Label htmlFor="answer" className="mb-0">
            Your answer
          </Label>
          {speech.supported && (
            <Segmented
              options={ANSWER_MODES}
              value={mode}
              variant="radio"
              size="sm"
              ariaLabel="How to answer"
              className="w-auto"
              onChange={(next) => {
                if (next === "text") speech.stop();
                setMode(next);
              }}
            />
          )}
        </div>

        {mode === "voice" && speech.supported && (
          <Card className="space-y-3 p-5">
            <div className="flex flex-wrap items-center gap-4">
              <button
                type="button"
                disabled={speech.preparing}
                onClick={() => {
                  if (speech.listening) {
                    speech.stop();
                    return;
                  }
                  cancelSpeech(); // don't transcribe our own question
                  speech.start();
                }}
                aria-label={speech.listening ? "Stop recording" : "Start recording your answer"}
                className={cn(
                  "relative flex h-14 w-14 shrink-0 items-center justify-center rounded-full",
                  "transition-all duration-200 disabled:opacity-50",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-void",
                  speech.listening
                    ? "animate-halo bg-missed text-white"
                    : "bg-gradient-to-br from-accent-deep to-accent text-white shadow-[0_10px_30px_-12px_rgba(139,92,246,1)] hover:brightness-110",
                )}
              >
                {speech.listening ? (
                  <Square aria-hidden="true" className="h-5 w-5 fill-current" />
                ) : (
                  <Mic aria-hidden="true" className="h-5 w-5" />
                )}
              </button>
              <span className="min-w-0 flex-1 text-sm text-muted" role="status" aria-live="polite">
                {speech.preparing
                  ? // Said out loud because it is a 40 MB download on a cold
                    // cache, and an unexplained ten-second button is a bug
                    // report. Once per session, then instant.
                    "Loading the on-device speech model — about 40 MB, once per session."
                  : speech.listening
                    ? "Listening — take your time, pauses are fine."
                    : hasAnswer
                      ? "Paused. Press start to add more, or submit."
                      : "Nothing recorded yet."}
              </span>
            </div>
            {speech.interim && (
              <p className="border-l-2 border-accent/40 pl-3 text-sm text-muted italic">
                {speech.interim}…
              </p>
            )}
            {speech.engine === "wasm" && (
              <p className="text-xs text-faint">
                Running on this device — your audio isn&rsquo;t leaving it.
              </p>
            )}
          </Card>
        )}

        <div>
          <Textarea
            id="answer"
            ref={answerRef}
            value={speech.text}
            onChange={(event) => speech.setText(event.target.value)}
            placeholder={
              mode === "voice"
                ? "What you say appears here. Edit it freely before submitting."
                : "Explain it however you'd explain it to a colleague. Plain words are fine."
            }
            aria-describedby="answer-help"
          />
          <p id="answer-help" className="mt-2 text-xs text-muted">
            Don&rsquo;t reach for the textbook term. Describe what actually happens.
            {mode === "voice" && " This text is what gets graded, so correct anything misheard."}
          </p>
        </div>

        {uncertain.length > 0 && (
          <Notice role="status" className="text-[0.8125rem]">
            <strong className="font-semibold text-partial">Worth checking.</strong> I
            wasn&rsquo;t confident I heard these correctly:{" "}
            {uncertain.map((segment) => `"${segment.text}"`).join(", ")}. They&rsquo;re graded as
            written above, so fix anything wrong.
          </Notice>
        )}

        <div className="flex flex-wrap gap-2 border-t border-line-soft pt-4">
          <Button type="submit" disabled={submit.isPending || !hasAnswer}>
            {submit.isPending ? "Submitting…" : "Submit answer"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={askHint.isPending || current.hints_used >= 3}
            onClick={() => askHint.mutate(current.question_id)}
          >
            <Lightbulb aria-hidden="true" className="h-3.5 w-3.5" />
            {current.hints_used >= 3
              ? "No hints left"
              : `Give me a hint (${3 - current.hints_used} left)`}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={submit.isPending}
            onClick={() => {
              speech.stop();
              submit.mutate({ questionId: current.question_id, text: "", skipped: true });
            }}
          >
            Skip
          </Button>
        </div>
        <p className="text-xs text-faint">Skipping is recorded as skipped, not as wrong.</p>
      </form>
    </Shell>
  );
}

/** One line of the consent disclosure: a bolded claim and its qualification. */
function Disclosure({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <p className="text-sm leading-relaxed text-muted">
      <strong className="font-semibold text-ink">{heading}</strong> {children}
    </p>
  );
}
