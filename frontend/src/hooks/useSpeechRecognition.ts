"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Dictation,
  type SpeechErrorEventLike,
  type SpeechRecognitionEventLike,
  type SpeechRecognitionLike,
  type TranscriptSegment,
  FINALIZE_TIMEOUT_MS,
  describeSpeechError,
  getRecognitionConstructor,
} from "@/lib/speech";

/**
 * Streaming speech-to-text in the browser (FR-V2).
 *
 * Interim results land in `interim` and are never committed; finalised ones
 * become timestamped segments (FR-V3) and are appended to `text`. The caller
 * owns `text` from then on, because **the candidate must be able to correct it
 * before submitting**: a recogniser mishearing "idempotent" as "I did potent"
 * would otherwise become a score, and FR-V4 is explicit that uncertainty is
 * surfaced rather than guessed at.
 *
 * Timings are measured against the moment recording started, not wall-clock, so
 * they stay meaningful as offsets into the answer.
 */
export function useSpeechRecognition(locale = "en-GB"): Dictation {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [durationMs, setDurationMs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const startedAt = useRef<number | null>(null);
  const elapsedBefore = useRef(0);
  const lastEnd = useRef(0);
  // `stop()` fires `onend` asynchronously, and so does an idle timeout. This
  // tells the two apart, so a browser that ends the session on its own gets
  // restarted instead of silently dropping the rest of the answer.
  const wantListening = useRef(false);
  // A mirror of what has been emitted. `finalize` runs inside an event handler
  // that already closed over the current render's state, so reading state
  // there would return the value from *before* the last result arrived.
  const latest = useRef({ text: "", segments: [] as TranscriptSegment[], durationMs: 0 });
  const finishedResolver = useRef<(() => void) | null>(null);

  useEffect(() => {
    setSupported(getRecognitionConstructor() !== null);
  }, []);

  const nowMs = useCallback(() => {
    const base = elapsedBefore.current;
    if (startedAt.current === null) return base;
    return base + Math.round(performance.now() - startedAt.current);
  }, []);

  const teardown = useCallback(() => {
    const instance = recognition.current;
    if (!instance) return;
    instance.onresult = null;
    instance.onerror = null;
    instance.onend = null;
    instance.onstart = null;
    try {
      instance.abort();
    } catch {
      // Already dead. Nothing to do, and nothing worth telling the user.
    }
    recognition.current = null;
  }, []);

  const start = useCallback(() => {
    const Recognition = getRecognitionConstructor();
    if (!Recognition || recognition.current) return;

    setError(null);
    const instance = new Recognition();
    instance.lang = locale; // FR-V6: parameterised by locale, not hardcoded.
    instance.continuous = true;
    instance.interimResults = true;
    instance.maxAlternatives = 1;

    instance.onstart = () => {
      startedAt.current = performance.now();
      setListening(true);
    };

    instance.onresult = (event: SpeechRecognitionEventLike) => {
      let pending = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const best = result?.[0];
        if (!result || !best) continue;

        if (!result.isFinal) {
          pending += best.transcript;
          continue;
        }

        const phrase = best.transcript.trim();
        if (!phrase) continue;

        const end = nowMs();
        const segment: TranscriptSegment = {
          text: phrase,
          start_ms: lastEnd.current,
          end_ms: end,
          // Chrome reports 0 for some finals rather than omitting it. Treating
          // a real 0 as "unknown" is the safer misread: it shows as uncertain
          // instead of asserting perfect confidence in a guess.
          confidence: best.confidence > 0 ? best.confidence : null,
        };
        lastEnd.current = end;
        latest.current = {
          text: latest.current.text ? `${latest.current.text} ${phrase}` : phrase,
          segments: [...latest.current.segments, segment],
          durationMs: end,
        };
        setSegments((current) => [...current, segment]);
        setText((current) => (current ? `${current} ${phrase}` : phrase));
        setDurationMs(end);
      }
      setInterim(pending);
    };

    instance.onerror = (event: SpeechErrorEventLike) => {
      // `aborted` is what our own stop() produces; never surface it.
      if (event.error === "aborted") return;
      // `no-speech` on a continuous session is a pause, not a failure.
      if (event.error === "no-speech") return;
      setError(describeSpeechError(event.error));
      wantListening.current = false;
    };

    instance.onend = () => {
      if (startedAt.current !== null) {
        elapsedBefore.current += Math.round(performance.now() - startedAt.current);
        startedAt.current = null;
        setDurationMs(elapsedBefore.current);
      }
      // Browsers end a "continuous" session after a stretch of silence. If the
      // candidate is still holding the mic open, start a new one — otherwise a
      // thinking pause silently ends their answer.
      if (wantListening.current) {
        recognition.current = null;
        start();
        return;
      }
      setListening(false);
      setInterim("");
      recognition.current = null;
      // Whatever the browser still owed us has now been delivered.
      finishedResolver.current?.();
    };

    recognition.current = instance;
    wantListening.current = true;
    try {
      instance.start();
    } catch {
      // Chrome throws if start() races a session that is still shutting down.
      wantListening.current = false;
      recognition.current = null;
      setError(describeSpeechError("unknown"));
    }
  }, [locale, nowMs]);

  const stop = useCallback(() => {
    wantListening.current = false;
    const instance = recognition.current;
    if (!instance) {
      setListening(false);
      return;
    }
    try {
      instance.stop(); // flushes any in-flight final result, unlike abort()
    } catch {
      teardown();
      setListening(false);
    }
  }, [teardown]);

  /**
   * G-006: stop, then wait for the final result the browser still owes us.
   *
   * `SpeechRecognition.stop()` is documented to flush any in-flight result
   * before firing `onend`, and that happens on a later tick — so reading the
   * transcript immediately after calling it loses the last phrase. This waits
   * for `onend`, then reads the refs (not state, which the caller's render has
   * already closed over).
   */
  const finalize = useCallback(async () => {
    if (!recognition.current) {
      return { text: latest.current.text, segments: latest.current.segments, durationMs };
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, FINALIZE_TIMEOUT_MS);
      finishedResolver.current = () => {
        clearTimeout(timer);
        resolve();
      };
      stop();
    });
    finishedResolver.current = null;
    return {
      text: latest.current.text,
      segments: latest.current.segments,
      durationMs: latest.current.durationMs,
    };
  }, [durationMs, stop]);

  // The candidate edits this box, and those edits are the transcript of record
  // (FR-V5). Routing them through the same mirror keeps `finalize` from
  // returning the pre-edit text and quietly undoing their corrections.
  const setTextAndMirror = useCallback((value: string) => {
    latest.current = { ...latest.current, text: value };
    setText(value);
  }, []);

  const reset = useCallback(() => {
    wantListening.current = false;
    teardown();
    startedAt.current = null;
    elapsedBefore.current = 0;
    lastEnd.current = 0;
    latest.current = { text: "", segments: [], durationMs: 0 };
    setListening(false);
    setText("");
    setInterim("");
    setSegments([]);
    setDurationMs(0);
    setError(null);
  }, [teardown]);

  // Leaving the room must release the microphone. A hot mic after navigation is
  // the kind of thing that ends trust in a product permanently.
  useEffect(() => {
    return () => {
      wantListening.current = false;
      teardown();
    };
  }, [teardown]);

  return {
    engine: "native",
    supported,
    listening,
    // Nothing to download: the recogniser is already in the browser. That is
    // the whole advantage this engine has over the on-device one.
    preparing: false,
    text,
    setText: setTextAndMirror,
    interim,
    segments,
    durationMs,
    error,
    start,
    stop,
    finalize,
    reset,
  };
}
