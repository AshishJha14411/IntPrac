import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { EdgeLight, GridGround } from "./backgrounds";

/** The page container. `wide` is the report and dashboard; everything else is narrow. */
export function Shell({
  children,
  width = "narrow",
  className,
}: {
  children: ReactNode;
  width?: "narrow" | "wide" | "tight";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-5 pt-10 pb-28 sm:px-6",
        width === "tight" && "max-w-md",
        width === "narrow" && "max-w-3xl",
        width === "wide" && "max-w-5xl",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * A page's title block, sitting on its own pool of light.
 *
 * The grid and the glow are `absolute` inside a `relative` wrapper that is
 * only as tall as the heading, so they frame the title rather than tinting
 * the whole scroll.
 */
export function PageHeader({
  title,
  lede,
  eyebrow,
  actions,
  className,
}: {
  title: ReactNode;
  lede?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("relative isolate mb-10", className)}>
      <GridGround className="-z-10 -mx-6 opacity-70" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 left-1/4 -z-10 h-64 w-[28rem] rounded-full bg-bloom-1 blur-[110px]"
      />
      {eyebrow && (
        <p className="mb-3 text-xs font-medium tracking-[0.18em] text-accent-soft/80 uppercase">
          {eyebrow}
        </p>
      )}
      <h1 className="text-gradient text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
        {title}
      </h1>
      {lede && (
        <p className="mt-4 max-w-2xl text-[0.975rem] leading-relaxed text-muted text-pretty">
          {lede}
        </p>
      )}
      {actions && <div className="mt-6 flex flex-wrap items-center gap-3">{actions}</div>}
    </header>
  );
}

/** A full-bleed band with a lit top edge, for the landing page's sections. */
export function Band({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("relative isolate", className)}>
      <EdgeLight />
      {children}
    </section>
  );
}
