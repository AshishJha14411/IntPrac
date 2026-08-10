"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDictation } from "@/hooks/useDictation";
import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { LOW_CONFIDENCE, type TranscriptSegment } from "@/lib/speech";
import type { AnswerResult, Hint, SessionPlan, Turn } from "@/lib/types";

type Mode = "voice" | "text";

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

  if (plan.isLoading) return <div className="shell">Loading…</div>;

  if (plan.isError) {
    const error = plan.error as ApiError;
    return (
      <div className="shell">
        <p className="error" role="alert">
          {error.code === "authentication-required"
            ? "Please sign in to continue."
            : error.message}
        </p>
      </div>
    );
  }

  // ── consent gate ────────────────────────────────────────────────────────
  if (status === "consent_pending" || status === "planned" || status === "device_check") {
    const allAccepted = consent.ai && consent.recording && consent.retention;
    return (
      <div className="shell">
        <h1>Before you start</h1>
        <div className="card stack">
          <p>
            <strong>An AI conducts and assesses this interview.</strong> A human is not watching
            it live.
          </p>
          <p>
            <strong>What is scored:</strong> whether your explanation of the mechanism is
            correct, how deep it goes, whether you ground it in specifics, and whether it is
            followable.
          </p>
          <p>
            <strong>What is never scored:</strong> your accent, fluency, grammar, speaking speed,
            confidence, or anything inferred from your face or voice. Terminology carries zero
            weight — the right idea in the wrong words is full credit.
          </p>
          <p>
            <strong>What is recorded:</strong> the transcript, whether you type it or speak it.
            This app stores and uploads <strong>no audio and no video</strong>.
            {speech.engine === "native" ? (
              <>
                {" "}
                Speaking uses your browser&rsquo;s built-in recognition, and some browsers —
                Chrome and Edge among them — send that audio to the browser vendor to
                transcribe it. Keeping it on this device, or typing, both avoid that and are
                scored identically.
              </>
            ) : (
              <>
                {" "}
                Speaking runs a speech model <strong>on this device</strong>, so your audio
                does not leave your machine at all.
              </>
            )}
          </p>
          <p className="muted small">
            Kept for up to <strong>6 months</strong>, then deleted automatically &mdash; transcripts
            included, not just files. You can delete this session, or your whole account, at
            any time from <a href="/dashboard">My interviews</a>.
          </p>

          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="visually-hidden">Consent</legend>
            {(
              [
                ["ai", "I understand an AI conducts and assesses this interview."],
                ["recording", "I consent to my transcript being recorded."],
                ["retention", "I understand the retention period and how to delete my data."],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="row" style={{ fontWeight: 400, marginBottom: 10 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={consent[key]}
                  onChange={(event) =>
                    setConsent((current) => ({ ...current, [key]: event.target.checked }))
                  }
                />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>

          <button
            disabled={!allAccepted || giveConsent.isPending || start.isPending}
            onClick={() => giveConsent.mutate()}
          >
            {giveConsent.isPending || start.isPending ? "Starting…" : "I agree — start"}
          </button>
          {!allAccepted && (
            <p className="small muted">
              All three are required. Without consent there is no session — that is deliberate.
            </p>
          )}
        </div>

        <h2>How you&rsquo;ll answer</h2>
        <div className="card stack">
          <p style={{ margin: 0 }}>
            Answers are <strong>spoken by default</strong>, the way an interview actually works.
            You can switch to typing at any point during the session, including mid-answer, and
            it is scored exactly the same — only the transcript is graded.
          </p>
          <div className="row">
            <button type="button" className="secondary" onClick={checkMicrophone}>
              Check my microphone
            </button>
            <span className="small muted" role="status">
              {mic === "granted" && "Microphone ready."}
              {mic === "blocked" && "Blocked — allow it in your browser, or just type instead."}
              {mic === "unknown" && "Worth doing now, so the prompt doesn't interrupt you."}
            </span>
          </div>
          <label className="row" style={{ fontWeight: 400, margin: 0 }}>
            <input
              type="checkbox"
              style={{ width: "auto" }}
              checked={onDevice || speech.engine === "wasm"}
              disabled={speech.engine === "wasm" && !onDevice}
              onChange={(event) => setOnDevice(event.target.checked)}
            />
            <span className="small">
              Keep my voice on this device.{" "}
              <span className="muted">
                {speech.engine === "wasm" && !onDevice
                  ? "Your browser has no built-in recognition, so this is the only option — and it is the more private one."
                  : "Runs the speech model locally instead of your browser's cloud one. One-off ~40 MB download, then nothing leaves your machine."}
              </span>
            </span>
          </label>
        </div>

        <h2>Your plan</h2>
        <p className="muted small">
          {plan.data?.questions.length} questions ·{" "}
          {plan.data?.session.seniority} level · {plan.data?.session.target_minutes} minutes
        </p>
        <ol className="small">
          {plan.data?.questions.map((question) => (
            <li key={question.id} style={{ marginBottom: 6 }}>
              <code>{question.competency_id}</code>{" "}
              <span className="muted">{question.competency_id.replace(/-/g, " ")}</span>
            </li>
          ))}
        </ol>
      </div>
    );
  }

  if (status && ["completed", "graded", "published", "reviewed"].includes(status)) {
    return (
      <div className="shell">
        <h1>Interview complete</h1>
        <p className="muted">Your report is being prepared.</p>
        <a href={`/report/${sessionId}`}>
          <button>Open my report</button>
        </a>
      </div>
    );
  }

  // ── turn loop ───────────────────────────────────────────────────────────
  const current = turn.data;
  if (!current) return <div className="shell">Loading the next question…</div>;

  const progress = ((current.ordinal + 1) / Math.max(1, current.total)) * 100;
  const submitError = submit.error as ApiError | null;
  const uncertain = speech.segments.filter(
    (segment) => segment.confidence !== null && segment.confidence < LOW_CONFIDENCE,
  );
  const hasAnswer = speech.text.trim().length > 0;

  return (
    <div className="shell">
      <div className="row small muted" style={{ justifyContent: "space-between" }}>
        <span>
          Question {current.ordinal + 1} of {current.total}
        </span>
        {/* An estimate, said as one. Nothing ends the session on time: this is
            practice, so every planned question gets asked however long it
            takes. A bare countdown would imply a deadline that does not
            exist. */}
        <span title="An estimate. Nothing cuts the session short — you'll get all the questions.">
          ~{current.remaining_minutes} min left (estimate)
        </span>
      </div>
      <div
        className="meter"
        role="progressbar"
        aria-valuenow={current.ordinal + 1}
        aria-valuemin={1}
        aria-valuemax={current.total}
        aria-label="Interview progress"
        style={{ margin: "8px 0 24px" }}
      >
        <span style={{ width: `${progress}%` }} />
      </div>

      <div className="card">
        <p className="small muted" style={{ margin: 0 }}>
          <code>{current.competency_id}</code>
        </p>
        <p style={{ fontSize: "1.15rem", margin: "10px 0 0" }} aria-live="polite">
          {currentPrompt}
        </p>
        {current.is_followup && (
          <p className="small muted" style={{ marginTop: 8, marginBottom: 0 }}>
            Follow-up on the same question — still the same topic, no new subject.
          </p>
        )}
        {voice.supported && (
          <div className="row" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="secondary"
              onClick={() => (voice.speaking ? voice.cancel() : voice.speak(currentPrompt ?? ""))}
            >
              {voice.speaking ? "Stop reading" : "Read the question again"}
            </button>
            <label className="row small muted" style={{ fontWeight: 400, margin: 0 }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={muted}
                onChange={(event) => setMuted(event.target.checked)}
              />
              <span>Don&rsquo;t read questions aloud</span>
            </label>
          </div>
        )}
      </div>

      {hints.map((hint, index) => (
        <div className="notice small" key={index} style={{ marginBottom: 10 }} role="status">
          <strong>Hint {index + 1}:</strong> {hint.text}
          <div className="muted" style={{ marginTop: 6 }}>
            {hint.scoring_note}
          </div>
        </div>
      ))}

      {submitError && (
        <p className="error" role="alert">
          {submitError.message}
        </p>
      )}
      {speech.error && (
        <p className="error" role="alert">
          {speech.error}
        </p>
      )}

      <form
        className="stack"
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
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <label htmlFor="answer">Your answer</label>
          {speech.supported && (
            <div className="row small" role="group" aria-label="How to answer">
              <button
                type="button"
                className={mode === "voice" ? undefined : "secondary"}
                aria-pressed={mode === "voice"}
                onClick={() => setMode("voice")}
              >
                Speak
              </button>
              <button
                type="button"
                className={mode === "text" ? undefined : "secondary"}
                aria-pressed={mode === "text"}
                onClick={() => {
                  speech.stop();
                  setMode("text");
                }}
              >
                Type
              </button>
            </div>
          )}
        </div>

        {mode === "voice" && speech.supported && (
          <div className="card stack" style={{ marginBottom: 0 }}>
            <div className="row">
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
              >
                {speech.preparing ? "Preparing…" : speech.listening ? "◼ Stop" : "● Start speaking"}
              </button>
              <span className="small muted" role="status" aria-live="polite">
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
              <p className="small muted" style={{ margin: 0, fontStyle: "italic" }}>
                {speech.interim}…
              </p>
            )}
            {speech.engine === "wasm" && (
              <p className="small muted" style={{ margin: 0 }}>
                Running on this device — your audio isn&rsquo;t leaving it.
              </p>
            )}
          </div>
        )}

        <textarea
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
        <p id="answer-help" className="small muted" style={{ marginTop: -4 }}>
          Don&rsquo;t reach for the textbook term. Describe what actually happens.
          {mode === "voice" && " This text is what gets graded, so correct anything misheard."}
        </p>

        {uncertain.length > 0 && (
          <div className="notice small" role="status">
            <strong>Worth checking.</strong> I wasn&rsquo;t confident I heard these correctly:{" "}
            {uncertain.map((segment) => `"${segment.text}"`).join(", ")}. They&rsquo;re graded as
            written above, so fix anything wrong.
          </div>
        )}

        <div className="row">
          <button type="submit" disabled={submit.isPending || !hasAnswer}>
            {submit.isPending ? "Submitting…" : "Submit answer"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={askHint.isPending || current.hints_used >= 3}
            onClick={() => askHint.mutate(current.question_id)}
          >
            {current.hints_used >= 3
              ? "No hints left"
              : `Give me a hint (${3 - current.hints_used} left)`}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={submit.isPending}
            onClick={() => {
              speech.stop();
              submit.mutate({ questionId: current.question_id, text: "", skipped: true });
            }}
          >
            Skip
          </button>
        </div>
        <p className="small muted">Skipping is recorded as skipped, not as wrong.</p>
      </form>
    </div>
  );
}
