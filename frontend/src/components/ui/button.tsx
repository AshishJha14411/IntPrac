import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "relative inline-flex select-none items-center justify-center gap-2 overflow-hidden rounded-xl " +
  "font-medium whitespace-nowrap transition-all duration-200 " +
  "disabled:pointer-events-none disabled:opacity-45 " +
  // Aceternity's snippets kill the outline; ours restores a ring in the same
  // rule, because a button nobody can see the focus on is a broken button.
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-void";

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[0.8125rem]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-[0.9375rem]",
};

const VARIANTS: Record<ButtonVariant, string> = {
  primary: cn(
    "bg-gradient-to-r from-accent-deep via-accent to-accent text-white",
    "shadow-glow",
    "hover:brightness-110 active:scale-[0.985]",
    // The light that sweeps across on hover.
    "before:absolute before:inset-0 before:-translate-x-full before:bg-gradient-to-r",
    "before:from-transparent before:via-white/30 before:to-transparent",
    "before:transition-transform before:duration-700 hover:before:translate-x-full",
    "motion-reduce:before:hidden",
  ),
  secondary: cn(
    "border border-line bg-glass-2 text-ink backdrop-blur-sm",
    "shadow-hairline",
    "hover:border-line-strong hover:bg-glass-3 active:scale-[0.985]",
  ),
  ghost: "text-muted hover:bg-glass-2 hover:text-ink",
  danger: cn(
    "border border-missed/40 bg-missed/10 text-missed",
    "hover:border-missed/70 hover:bg-missed/20 active:scale-[0.985]",
  ),
};

export function buttonClasses({
  variant = "primary",
  size = "md",
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
} = {}): string {
  return cn(BASE, SIZES[size], VARIANTS[variant], className);
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button className={buttonClasses({ variant, size, className })} {...rest}>
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </button>
  );
}

/**
 * A link that looks like a button.
 *
 * Not `<Link><button/></Link>`, which was the old shape: an interactive
 * element inside an anchor is invalid HTML and gives assistive technology two
 * nested controls to announce for one target. This is one control that
 * navigates.
 */
export function LinkButton({
  href,
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
} & Omit<React.ComponentProps<typeof Link>, "href" | "className" | "children">) {
  return (
    <Link href={href} className={buttonClasses({ variant, size, className })} {...rest}>
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </Link>
  );
}

/**
 * The rotating conic border. Aceternity's most recognisable button, and pure
 * CSS: a 1px-padded pill containing an oversized spinning gradient, with an
 * opaque inner pill sitting on top of all but the edge.
 */
export function GradientBorderLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "group relative inline-flex h-12 overflow-hidden rounded-full p-px",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-void",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="absolute inset-[-1000%] animate-orbit bg-[conic-gradient(from_90deg_at_50%_50%,#c4b5fd_0%,#4f46e5_50%,#22d3ee_100%)] motion-reduce:animate-none"
      />
      <span
        className={cn(
          "relative inline-flex h-full w-full items-center justify-center gap-2 rounded-full",
          "bg-void px-7 text-sm font-medium text-ink backdrop-blur-3xl",
          "transition-colors duration-300 group-hover:bg-panel",
        )}
      >
        {children}
      </span>
    </Link>
  );
}
