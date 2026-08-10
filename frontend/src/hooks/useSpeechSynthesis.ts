"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isSynthesisSupported } from "@/lib/speech";

/**
 * Reading the question aloud (FR-V1).
 *
 * NFR-C2 asks for TTS cached permanently per (question, voice, version) so the
 * marginal cost approaches zero. `speechSynthesis` reaches the same end by a
 * shorter route: it renders on the device, so a re-ask costs nothing because
 * there was never anything to pay for or to cache. The trade is voice quality
 * and consistency across machines — see ADR 011 for when that stops being an
 * acceptable trade.
 *
 * Deliberately never autoplays. A page that starts talking on load is hostile
 * to screen-reader users, whose own output it talks over.
 */
export type UseSpeechSynthesis = {
  supported: boolean;
  speaking: boolean;
  speak: (text: string) => void;
  cancel: () => void;
};

export function useSpeechSynthesis(locale = "en-GB"): UseSpeechSynthesis {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    setSupported(isSynthesisSupported());
  }, []);

  const cancel = useCallback(() => {
    if (!isSynthesisSupported()) return;
    window.speechSynthesis.cancel();
    utterance.current = null;
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (!isSynthesisSupported() || !text.trim()) return;
      // Queued utterances accumulate; a second press should replace, not stack.
      window.speechSynthesis.cancel();

      const next = new SpeechSynthesisUtterance(text);
      next.lang = locale;
      next.rate = 0.95; // a shade under default — question prose, not a bulletin
      next.onend = () => setSpeaking(false);
      next.onerror = () => setSpeaking(false);
      utterance.current = next;
      setSpeaking(true);
      window.speechSynthesis.speak(next);
    },
    [locale],
  );

  // Navigating away mid-sentence must stop the voice: `speechSynthesis` lives
  // on `window`, so it outlives the component that started it.
  useEffect(() => cancel, [cancel]);

  return { supported, speaking, speak, cancel };
}
