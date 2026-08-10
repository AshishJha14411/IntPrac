"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Dictation,
  type TranscriptSegment,
  FINALIZE_TIMEOUT_MS,
  VOSK_MODEL_URL,
} from "@/lib/speech";

/**
 * Speech-to-text with the model running **on this device**.
 *
 * Why this exists: the browser's own `SpeechRecognition` does not exist in
 * Firefox, and "install Chrome" is the answer that quietly excludes people —
 * which is the opposite of the point of having two input modes at all. A Vosk
 * model in a worker works in every browser, and it is a privacy upgrade rather
 * than a compromise: Chrome and Edge transcribe in the cloud, this does not
 * leave the machine.
 *
 * Vosk is the right engine here rather than Whisper because the requirements
 * already ask for what it emits. `setWords(true)` returns
 * `{word, start, end, conf}` per word, which is FR-V3's timings and FR-V4's
 * confidence directly, and it streams genuine partial results (FR-V2) instead
 * of Whisper's fixed-window chunks.
 *
 * The interface is identical to `useSpeechRecognition` on purpose — see
 * `Dictation`.
 */

/** Vosk reports seconds; the wire format and the database are milliseconds. */
const toMs = (seconds: number) => Math.round(seconds * 1000);

/** Vosk's own recommended sample rate for the small English models. */
const TARGET_SAMPLE_RATE = 16_000;

type VoskWord = { conf: number; start: number; end: number; word: string };

export function useWasmRecognition(): Dictation {
  const [listening, setListening] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [durationMs, setDurationMs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // The model is expensive to load and cheap to keep, so it outlives a single
  // answer: the download is paid once per session, not once per question.
  const model = useRef<Awaited<ReturnType<typeof loadVosk>> | null>(null);
  const recognizer = useRef<{
    acceptWaveformFloat: (b: Float32Array, r: number) => void;
    retrieveFinalResult: () => void;
    remove: () => void;
  } | null>(null);
  // Same reason as the native hook: `finalize` runs inside a handler that has
  // already closed over this render's state.
  const latest = useRef({ text: "", segments: [] as TranscriptSegment[], durationMs: 0 });
  const finishedResolver = useRef<(() => void) | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const startedAt = useRef<number | null>(null);
  const elapsedBefore = useRef(0);

  const nowMs = useCallback(() => {
    const base = elapsedBefore.current;
    if (startedAt.current === null) return base;
    return base + Math.round(performance.now() - startedAt.current);
  }, []);

  const releaseMicrophone = useCallback(() => {
    // Order matters: detach the graph before killing the tracks, or Firefox
    // logs a stream of errors from a worklet reading a dead source.
    audio.current?.close().catch(() => undefined);
    audio.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);

  const stop = useCallback(() => {
    releaseMicrophone();
    if (startedAt.current !== null) {
      elapsedBefore.current += Math.round(performance.now() - startedAt.current);
      startedAt.current = null;
      setDurationMs(elapsedBefore.current);
    }
    setListening(false);
    setInterim("");
  }, [releaseMicrophone]);

  const start = useCallback(async () => {
    if (listening || preparing) return;
    setError(null);
    setPreparing(true);
    try {
      // 1. The model. First call downloads it; later calls are instant, and
      //    the browser's HTTP cache keeps it across reloads.
      if (!model.current) {
        model.current = await loadVosk(VOSK_MODEL_URL);
      }

      // 2. The microphone. Echo cancellation and noise suppression are on:
      //    this is someone talking through a laptop mic in a room, and the
      //    model was not trained on their air conditioning.
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
      stream.current = media;

      // 3. Ask for 16 kHz directly. Browsers may refuse and hand back their
      //    native rate, so the recogniser is told whatever we actually got
      //    rather than what we asked for -- a mismatch here does not error, it
      //    just transcribes gibberish, which is far harder to notice.
      const context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      audio.current = context;
      const sampleRate = context.sampleRate;

      const kaldi = new model.current.KaldiRecognizer(sampleRate);
      kaldi.setWords(true); // FR-V3/V4: per-word timings and confidence
      recognizer.current = kaldi;

      kaldi.on("partialresult", (message) => {
        const partial = (message as { result?: { partial?: string } }).result?.partial;
        setInterim(partial ?? "");
      });

      kaldi.on("result", (message) => {
        const payload = (message as { result?: { text?: string; result?: VoskWord[] } }).result;
        const phrase = payload?.text?.trim();
        if (!phrase) return;
        const words = payload?.result ?? [];
        const segment = toSegment(phrase, words, nowMs());
        latest.current = {
          text: latest.current.text ? `${latest.current.text} ${phrase}` : phrase,
          segments: [...latest.current.segments, segment],
          durationMs: nowMs(),
        };
        setSegments((current) => [...current, segment]);
        setText((current) => (current ? `${current} ${phrase}` : phrase));
        setInterim("");
        setDurationMs(nowMs());
        // If this is the flush `finalize` asked for, release it.
        finishedResolver.current?.();
      });

      // 4. Feed it. The worklet copies frames off the audio thread; see
      //    public/audio/pcm-worklet.js for why that is not a ScriptProcessor.
      await context.audioWorklet.addModule("/audio/pcm-worklet.js");
      const source = context.createMediaStreamSource(media);
      const tap = new AudioWorkletNode(context, "pcm-worklet");
      tap.port.onmessage = (event: MessageEvent<Float32Array>) => {
        recognizer.current?.acceptWaveformFloat(event.data, sampleRate);
      };
      source.connect(tap);
      // Terminate the graph without routing audio to the speakers — connecting
      // a live microphone to `destination` is how you get feedback howl.
      tap.connect(context.createGain()).connect(context.destination);

      startedAt.current = performance.now();
      setListening(true);
    } catch (cause) {
      releaseMicrophone();
      setError(describeWasmError(cause));
      setListening(false);
    } finally {
      setPreparing(false);
    }
  }, [listening, preparing, nowMs, releaseMicrophone]);

  /**
   * G-006: Vosk holds its last words until asked for them.
   *
   * `stop()` alone detaches the microphone and clears the partial text without
   * ever finalising it, so the tail of an answer was simply discarded.
   * `retrieveFinalResult()` makes the worker emit one last `result` event; we
   * wait for it, with a timeout so a worker that never answers cannot hold a
   * submit open.
   */
  const finalize = useCallback(async () => {
    const kaldi = recognizer.current;
    if (!kaldi) {
      return { ...latest.current };
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, FINALIZE_TIMEOUT_MS);
      finishedResolver.current = () => {
        clearTimeout(timer);
        resolve();
      };
      try {
        kaldi.retrieveFinalResult();
      } catch {
        clearTimeout(timer);
        resolve();
      }
    });
    finishedResolver.current = null;
    stop();
    return { ...latest.current };
  }, [stop]);

  const reset = useCallback(() => {
    stop();
    recognizer.current?.remove();
    recognizer.current = null;
    elapsedBefore.current = 0;
    latest.current = { text: "", segments: [], durationMs: 0 };
    setText("");
    setInterim("");
    setSegments([]);
    setDurationMs(0);
    setError(null);
  }, [stop]);

  // Leaving the room must release the microphone and the worker. A hot mic
  // after navigation ends trust in a product permanently.
  useEffect(() => {
    return () => {
      releaseMicrophone();
      recognizer.current?.remove();
      recognizer.current = null;
      model.current?.terminate();
      model.current = null;
    };
  }, [releaseMicrophone]);

  return {
    engine: "wasm",
    supported: true, // WASM + getUserMedia is everywhere we care about
    listening,
    preparing,
    text,
    setText: (value: string) => {
      // Candidate edits are the transcript of record; keep the mirror in step.
      latest.current = { ...latest.current, text: value };
      setText(value);
    },
    interim,
    segments,
    durationMs,
    error,
    start: () => {
      void start();
    },
    stop,
    finalize,
    reset,
  };
}

/**
 * Turn one Vosk result into one stored segment.
 *
 * Confidence is the **minimum** across the words, not the mean: a phrase is
 * only as trustworthy as its least trustworthy word, and averaging is exactly
 * how one badly-heard technical term hides behind nine easy ones. FR-V4 wants
 * the uncertainty surfaced, so this rounds towards flagging it.
 */
function toSegment(phrase: string, words: VoskWord[], fallbackEnd: number): TranscriptSegment {
  if (words.length === 0) {
    return { text: phrase, start_ms: fallbackEnd, end_ms: fallbackEnd, confidence: null };
  }
  return {
    text: phrase,
    start_ms: toMs(Math.min(...words.map((word) => word.start))),
    end_ms: toMs(Math.max(...words.map((word) => word.end))),
    confidence: Math.min(...words.map((word) => word.conf)),
  };
}

/** Imported lazily: the package pulls in ~5 MB of WASM glue. */
async function loadVosk(modelUrl: string) {
  const vosk = await import("vosk-browser");
  return vosk.createModel(modelUrl);
}

function describeWasmError(cause: unknown): string {
  const name = cause instanceof Error ? cause.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access was blocked. Allow it in your browser, or switch to typing.";
  }
  if (name === "NotFoundError") {
    return "No microphone was found. Plug one in, or switch to typing.";
  }
  return "The on-device speech model could not start. You can keep going by typing.";
}
