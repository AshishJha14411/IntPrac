import { cn } from "@/lib/cn";

/**
 * Ambient layers.
 *
 * All four are pure CSS/SVG and carry no state, so they stay Server
 * Components — none of the "use client" cost of an aesthetic. Each one is
 * `aria-hidden` and `pointer-events-none`: decoration a screen reader should
 * never announce and a cursor should never hit.
 */

/** The blurred beam that rakes across a hero. Aceternity's signature entrance. */
export function Spotlight({ className, fill = "var(--color-spotlight)" }: { className?: string; fill?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute z-0 h-[169%] w-[138%] opacity-0 animate-spotlight lg:w-[84%]",
        className,
      )}
      viewBox="0 0 3787 2842"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g filter="url(#spotlight-blur)">
        <ellipse
          cx="1924.71"
          cy="273.501"
          rx="1924.71"
          ry="273.501"
          transform="matrix(-0.822377 -0.568943 -0.568943 0.822377 3631.88 2291.09)"
          fill={fill}
          fillOpacity="0.16"
        />
      </g>
      <defs>
        <filter
          id="spotlight-blur"
          x="0.860352"
          y="0.838989"
          width="3785.16"
          height="2840.26"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="151" result="blur" />
        </filter>
      </defs>
    </svg>
  );
}

/** Slow violet/cyan blooms behind the content. */
export function Aurora({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}
    >
      <div className="absolute -top-40 left-[8%] h-[34rem] w-[34rem] rounded-full bg-bloom-1 blur-[120px] animate-aurora" />
      <div className="absolute -top-24 right-[4%] h-[28rem] w-[28rem] rounded-full bg-bloom-2 blur-[130px] animate-drift" />
      <div className="absolute top-[42%] left-[38%] h-[24rem] w-[24rem] rounded-full bg-bloom-3 blur-[140px] animate-aurora" />
    </div>
  );
}

/**
 * The faint lattice, masked to fade out at the edges so it reads as depth
 * rather than as graph paper.
 */
export function GridGround({
  variant = "grid",
  className,
}: {
  variant?: "grid" | "dots";
  className?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0",
        variant === "grid" ? "bg-lattice" : "bg-dotted",
        "[mask-image:radial-gradient(ellipse_at_center,black_5%,transparent_72%)]",
        className,
      )}
    />
  );
}

/** A hairline of light along the top edge of a section. */
export function EdgeLight({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-x-0 top-0 h-px",
        "bg-gradient-to-r from-transparent via-accent-soft/45 to-transparent",
        className,
      )}
    />
  );
}
