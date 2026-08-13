import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { GlowCard } from "./card";

/** The Aceternity bento grid: uneven tiles that still line up. */
export function BentoGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}>{children}</div>
  );
}

export function BentoCard({
  step,
  title,
  children,
  className,
  icon,
}: {
  step?: string;
  title: ReactNode;
  children: ReactNode;
  className?: string;
  icon?: ReactNode;
}) {
  return (
    <GlowCard className={cn("h-full", className)}>
      <div className="flex h-full flex-col gap-3 p-6">
        <div className="flex items-center gap-3">
          {icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-gradient-to-br from-accent/25 to-accent-cool/10 text-accent-soft">
              {icon}
            </span>
          )}
          {step && (
            <span className="font-mono text-xs tracking-widest text-faint uppercase">{step}</span>
          )}
        </div>
        <h3 className="text-base font-semibold tracking-tight text-ink">{title}</h3>
        <div className="text-sm leading-relaxed text-muted">{children}</div>
      </div>
    </GlowCard>
  );
}
