/**
 * The Web Speech API, typed.
 *
 * `lib.dom.d.ts` does not ship these — the spec is still a draft and every
 * engine that implements recognition does so behind `webkitSpeechRecognition`.
 * Declaring the shape here keeps the hooks honest instead of `any`-ing over the
 * one place where the browser is lying to us most often.
 *
 * Support, as of writing: Chrome, Edge and Safari implement recognition;
 * Firefox does not. That is not an edge case to paper over — see
 * `isRecognitionSupported`, and the text path the interview room falls back to.
 */

export type SpeechAlternative = { transcript: string; confidence: number };

export type SpeechResult = {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechAlternative;
};

export type SpeechResultList = { length: number; [index: number]: SpeechResult };

export type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: SpeechResultList;
};

/** `no-speech` and `aborted` are routine; the rest are worth showing a user. */
export type SpeechErrorEventLike = { error: string; message?: string };

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechErrorEventLike) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

type RecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechWindow = Window & {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
};

export function getRecognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const scope = window as SpeechWindow;
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export function isRecognitionSupported(): boolean {
  return getRecognitionConstructor() !== null;
}

export function isSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** FR-V2/V3: one finalised span, timestamped against the answer's own clock. */
export type TranscriptSegment = {
  text: string;
  start_ms: number;
  end_ms: number;
  confidence: number | null;
};

/**
 * Which recogniser is doing the work.
 *
 * - `native` — the browser's own `SpeechRecognition`. Instant, but Chrome and
 *   Edge transcribe it in the cloud, so the audio leaves the machine.
 * - `wasm` — a Vosk model running in a worker on this device. Costs a one-off
 *   download; the audio never leaves.
 * - `none` — neither is available. Typing, which is a peer and not a penalty.
 */
export type DictationEngine = "native" | "wasm" | "none";

/**
 * The contract the interview room codes against.
 *
 * Both engines implement it, so the room never branches on which one is
 * running — which is what stops "Firefox users" becoming a second code path
 * that quietly rots.
 */
export type Dictation = {
  engine: DictationEngine;
  supported: boolean;
  listening: boolean;
  /** Finalised text. Owned by the caller once emitted — edits are expected. */
  text: string;
  setText: (value: string) => void;
  /** The in-flight phrase. Shown live, never submitted as-is. */
  interim: string;
  segments: TranscriptSegment[];
  durationMs: number;
  error: string | null;
  /** `wasm` only: the model is downloading or warming up. */
  preparing: boolean;
  start: () => void;
  stop: () => void;
  /**
   * Stop, wait for the recogniser to emit whatever it was still holding, and
   * resolve with the finished transcript.
   *
   * G-006. Submitting called `stop()` and sent the render's current text in
   * the same tick — but both engines finalise **asynchronously**: the native
   * one flushes its last result on `onend`, and Vosk only emits its final
   * words when asked. So the end of an answer could be missing from the
   * transcript, and therefore from the score, on a product whose transcript is
   * the artifact of record (FR-V5).
   *
   * Resolving with the text rather than relying on React state is the point: a
   * setState from the final result would not be visible to the submit handler
   * that is already running.
   */
  finalize: () => Promise<{ text: string; segments: TranscriptSegment[]; durationMs: number }>;
  reset: () => void;
};

/**
 * How long to wait for a recogniser to hand over its last words.
 *
 * Generous enough that a normal flush always lands, short enough that a
 * recogniser which never fires its end event cannot hold a submit hostage —
 * whatever has been transcribed by then is submitted anyway.
 */
export const FINALIZE_TIMEOUT_MS = 1500;

/**
 * Where the Vosk model is served from.
 *
 * Not committed to the repo — it is ~40 MB. `npm run fetch:model` puts it in
 * `public/models/`, and the Docker build does the same. Point this at a CDN or
 * a bucket instead if you would rather not ship it with the app.
 */
export const VOSK_MODEL_URL =
  process.env.NEXT_PUBLIC_VOSK_MODEL_URL ?? "/models/vosk-model-small-en-us-0.15.tar.gz";

/**
 * FR-V4 mirrored client-side, for display only.
 *
 * The server re-derives this and its answer is the one that gets stored — a
 * client deciding what counts as uncertain about its own output is not a check.
 */
export const LOW_CONFIDENCE = 0.6;

/** Human-readable reasons, so the UI never shows a raw spec string. */
export function describeSpeechError(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access was blocked. Allow it in your browser, or switch to typing.";
    case "audio-capture":
      return "No microphone was found. Plug one in, or switch to typing.";
    case "network":
      return "Speech recognition needs a network connection. You can type instead.";
    case "no-speech":
      return "I didn't catch anything. Try again, or type your answer.";
    default:
      return "Speech recognition stopped unexpectedly. You can keep going by typing.";
  }
}
