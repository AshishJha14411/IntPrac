"use client";

import { motion, useMotionTemplate, useMotionValue } from "motion/react";
import type { MouseEvent, ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * The surface everything sits on.
 *
 * Aceternity's card is not a lighter grey box — it is translucent white over
 * the page's own darkness, with a hairline border and a highlight along the
 * top edge that suggests light falling from above. That reads as depth on a
 * near-black ground where a solid `#171a21` reads as a patch.
 */
export function Card({
  children,
  className,
  as: Tag = "div",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article" | "li";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={cn(
        "relative overflow-hidden rounded-2xl border border-line",
        "bg-glass bg-gradient-to-b from-sheen to-transparent",
        "shadow-card",
        "backdrop-blur-sm",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * A card that lights up under the cursor.
 *
 * The radial gradient tracks the pointer through a motion value rather than
 * React state: state would re-render the subtree on every `mousemove`, which
 * on the report page means re-rendering a dozen concept lists at 60 Hz. The
 * motion value writes straight to the style, so React never runs.
 *
 * Purely decorative — the same content is fully legible with the glow off,
 * which is what `prefers-reduced-motion` and touch devices get.
 */
export function GlowCard({
  children,
  className,
  glow = "var(--color-glow)",
}: {
  children: ReactNode;
  className?: string;
  glow?: string;
}) {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  function track({ currentTarget, clientX, clientY }: MouseEvent<HTMLDivElement>) {
    const bounds = currentTarget.getBoundingClientRect();
    mouseX.set(clientX - bounds.left);
    mouseY.set(clientY - bounds.top);
  }

  const background = useMotionTemplate`radial-gradient(360px circle at ${mouseX}px ${mouseY}px, ${glow}, transparent 70%)`;

  return (
    <div
      onMouseMove={track}
      className={cn(
        "group relative overflow-hidden rounded-2xl border border-line",
        "bg-glass bg-gradient-to-b from-sheen to-transparent",
        "shadow-card",
        "transition-colors duration-300 hover:border-line-strong",
        className,
      )}
    >
      <motion.div
        aria-hidden="true"
        style={{ background }}
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100 motion-reduce:hidden"
      />
      <div className="relative">{children}</div>
    </div>
  );
}

/**
 * A card wrapped in a gradient hairline instead of a flat border — used where
 * a surface needs to be the loudest thing on the page (the overall verdict,
 * the auth form) without resorting to a bigger heading.
 */
export function GradientCard({
  children,
  className,
  innerClassName,
}: {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
}) {
  return (
    <div
      className={cn(
        "relative rounded-2xl bg-gradient-to-br from-accent/45 via-accent-deep/20 to-accent-cool/30 p-px",
        className,
      )}
    >
      <div
        className={cn(
          "relative h-full overflow-hidden rounded-[calc(1rem-1px)] bg-panel/95 backdrop-blur-xl",
          innerClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}
