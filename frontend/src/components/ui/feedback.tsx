import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Verdict } from "@/lib/types";

/**
 * Status surfaces.
 *
 * The one rule the restyle could not bend: **colour is never the only
 * signal** (NFR-A / WCAG 2.2 AA). A violet-on-black design is a strong
 * temptation to encode meaning in a hue, so every chip below still carries a
 * glyph and a word, and every notice still carries a heading or a role.
 */

export function Notice({
  children,
  className,
  tone = "neutral",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "accent";
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border p-4 text-sm leading-relaxed",
        tone === "accent"
          ? "border-accent/30 bg-accent/[0.07] text-ink"
          : "border-line bg-glass-2 text-ink/90",
        className,
      )}
      {...rest}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-y-0 left-0 w-px",
          tone === "accent"
            ? "bg-gradient-to-b from-transparent via-accent to-transparent"
            : "bg-gradient-to-b from-transparent via-line-strong to-transparent",
        )}
      />
      {children}
    </div>
  );
}

export function ErrorNote({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-xl border border-missed/35 bg-missed/[0.08] p-3.5",
        "text-sm leading-relaxed text-missed",
        className,
      )}
      {...rest}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        className="mt-0.5 h-4 w-4 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      >
        <circle cx="10" cy="10" r="7.5" />
        <path d="M10 6.25v4.5M10 13.4v.2" />
      </svg>
      <span className="min-w-0">{children}</span>
    </div>
  );
}

/** A small neutral pill. Text carries the meaning; the tint is decoration. */
export function Badge({
  children,
  className,
  tone = "neutral",
}: {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "accent" | "mono";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        tone === "accent" && "border-accent/35 bg-accent/12 text-accent-soft",
        tone === "neutral" && "border-line bg-glass-2 text-muted",
        tone === "mono" && "border-line bg-glass-2 font-mono text-[0.7rem] text-accent-soft",
        className,
      )}
    >
      {children}
    </span>
  );
}

const VERDICTS: Record<Verdict, { glyph: string; ring: string; text: string; bar: string }> = {
  covered: { glyph: "✓", ring: "border-covered/40 bg-covered/10", text: "text-covered", bar: "bg-covered" },
  partial: { glyph: "◐", ring: "border-partial/40 bg-partial/10", text: "text-partial", bar: "bg-partial" },
  missing: { glyph: "○", ring: "border-missed/40 bg-missed/10", text: "text-missed", bar: "bg-missed" },
  contradicted: { glyph: "✕", ring: "border-missed/40 bg-missed/10", text: "text-missed", bar: "bg-missed" },
};

/** Glyph + word + hue, in that order of importance. */
export function VerdictChip({ verdict }: { verdict: Verdict }) {
  const style = VERDICTS[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
        style.ring,
        style.text,
      )}
    >
      <span aria-hidden="true">{style.glyph}</span>
      {verdict}
    </span>
  );
}

export function verdictBar(verdict: Verdict): string {
  return VERDICTS[verdict].bar;
}

/**
 * A progress bar.
 *
 * The ARIA values are passed in rather than derived from `percent`, because
 * the two callers measure different things: the dashboard reports a score out
 * of 100, the interview room reports question 3 of 8. Announcing "37%" for
 * the latter would be wrong.
 */
export function Meter({
  percent,
  valueNow,
  valueMin = 0,
  valueMax = 100,
  ariaLabel,
  className,
  tone = "accent",
}: {
  percent: number;
  valueNow: number;
  valueMin?: number;
  valueMax?: number;
  ariaLabel: string;
  className?: string;
  tone?: "accent" | "covered" | "partial" | "missed";
}) {
  const fill = {
    accent: "from-accent-deep via-accent to-accent-cool",
    covered: "from-covered/70 to-covered",
    partial: "from-partial/70 to-partial",
    missed: "from-missed/70 to-missed",
  }[tone];

  return (
    <div
      role="progressbar"
      aria-valuenow={valueNow}
      aria-valuemin={valueMin}
      aria-valuemax={valueMax}
      aria-label={ariaLabel}
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full border border-line-soft bg-glass-2",
        className,
      )}
    >
      <div
        className={cn(
          "h-full rounded-full bg-gradient-to-r transition-[width] duration-500 ease-out",
          fill,
        )}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  );
}

/** Section heading with the hairline rule Aceternity puts under everything. */
export function SectionHeading({
  children,
  hint,
  className,
}: {
  children: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mt-12 mb-4 flex flex-wrap items-baseline justify-between gap-3", className)}>
      <h2 className="text-xl font-semibold tracking-tight text-ink">{children}</h2>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}
