"use client";

import { motion, useReducedMotion } from "motion/react";
import { useId, useRef } from "react";
import { cn } from "@/lib/cn";

/**
 * The Aceternity animated tab strip: the highlight is one element that slides
 * between options via a shared `layoutId`, rather than a background that
 * appears and disappears on each button.
 *
 * Two semantics, because the app has two genuinely different pickers:
 *
 * - `"tab"` — a tablist, for choosing which form you are filling in.
 * - `"radio"` — a radiogroup, for choosing between two equivalent ways of
 *   doing the same thing (speak vs type). A screen reader announces "2 of 2,
 *   selected", which is the truth; two independent toggle buttons would not
 *   convey that picking one unpicks the other.
 *
 * Both roles come with a keyboard contract, and taking the role without the
 * contract is worse than using plain buttons: the strip is **one** tab stop,
 * and the arrow keys move within it. Implemented below rather than assumed,
 * because the div-and-onClick version of this component passes a glance and
 * fails a keyboard.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  variant = "tab",
  size = "md",
  className,
}: {
  options: readonly { value: T; label: string; disabled?: boolean }[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  variant?: "tab" | "radio";
  size?: "sm" | "md";
  className?: string;
}) {
  const layoutId = useId();
  const reduced = useReducedMotion();
  const strip = useRef<HTMLDivElement>(null);
  const isTab = variant === "tab";

  const selectable = options.filter((option) => !option.disabled);

  /** Home/End/arrows move selection, and move focus with it. */
  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();

    const at = selectable.findIndex((option) => option.value === value);
    const last = selectable.length - 1;
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? last
          : event.key === "ArrowLeft" || event.key === "ArrowUp"
            ? (at <= 0 ? last : at - 1)
            : (at >= last ? 0 : at + 1);

    const target = selectable[next];
    if (!target) return;
    onChange(target.value);
    // The newly-selected control is the only one in the tab order, so focus
    // has to follow the selection or the next Tab leaves the strip entirely.
    strip.current
      ?.querySelector<HTMLButtonElement>(`[data-segment="${CSS.escape(target.value)}"]`)
      ?.focus();
  }

  return (
    <div
      ref={strip}
      role={isTab ? "tablist" : "radiogroup"}
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex w-full flex-wrap gap-1 rounded-xl border border-line bg-glass-2 p-1",
        "shadow-hairline",
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            data-segment={option.value}
            role={isTab ? "tab" : "radio"}
            aria-selected={isTab ? selected : undefined}
            aria-checked={isTab ? undefined : selected}
            // Roving tabindex: one stop for the whole group.
            tabIndex={selected ? 0 : -1}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative flex-1 rounded-lg font-medium whitespace-nowrap transition-colors duration-200",
              size === "sm" ? "px-3 py-1.5 text-[0.8125rem]" : "px-4 py-2 text-sm",
              selected ? "text-ink" : "text-muted hover:text-ink",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft",
              "disabled:pointer-events-none disabled:opacity-45",
            )}
          >
            {selected && (
              <motion.span
                aria-hidden="true"
                layoutId={layoutId}
                transition={
                  reduced ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 34 }
                }
                className={cn(
                  "absolute inset-0 rounded-lg border border-line",
                  "bg-gradient-to-b from-sheen-strong to-sheen",
                  "shadow-pill",
                )}
              />
            )}
            <span className="relative z-10">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
