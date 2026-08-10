"use client";

import { useEffect, useState } from "react";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useWasmRecognition } from "@/hooks/useWasmRecognition";
import { type Dictation, isRecognitionSupported } from "@/lib/speech";

/**
 * Pick a recogniser. The interview room never learns which one it got.
 *
 * Default order, and the reasoning:
 *
 * 1. **The browser's own** where it exists (Chrome, Edge, Safari). Nothing to
 *    download, starts instantly, and it is what most candidates will hit.
 * 2. **The on-device model** otherwise — Firefox, chiefly. Costs a one-off
 *    ~40 MB download and then works identically. This is the branch that stops
 *    "which browser are you using?" from deciding whether someone gets to
 *    speak at all.
 *
 * `prefer` lets the room override, which is not a developer toggle: choosing
 * the on-device engine is how a candidate keeps their audio off Google's
 * servers, and that is a decision for them rather than for us.
 *
 * Both hooks run unconditionally — React requires a stable hook order, and the
 * unselected one holds no microphone, no worker and no model until something
 * calls `start()`.
 */
export function useDictation(prefer?: "native" | "wasm"): Dictation {
  const native = useSpeechRecognition();
  const wasm = useWasmRecognition();
  const [hasNative, setHasNative] = useState(false);

  // After mount: the server render has no `window` to ask, and a mode that
  // flickers on hydration reads as a bug.
  useEffect(() => {
    setHasNative(isRecognitionSupported());
  }, []);

  if (prefer === "wasm") return wasm;
  if (prefer === "native") return native;
  return hasNative ? native : wasm;
}
