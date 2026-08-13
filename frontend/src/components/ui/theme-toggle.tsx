"use client";

import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * The theme switch.
 *
 * Deliberately **stateless**. It writes `data-theme` on `<html>` and lets CSS
 * do the rest; which icon shows is a `light:` variant, not a render.
 *
 * That is not a micro-optimisation, it is what makes the button correct. A
 * `useState` version cannot know the theme during the server render — the
 * choice lives in `localStorage`, which the server has never seen — so it
 * either renders the wrong icon and hydration-mismatches, or renders nothing
 * until an effect runs and the control visibly pops in. Neither happens if
 * React is not the thing deciding.
 *
 * The accessible name stays constant for the same reason: a name that flipped
 * with the theme would have to be rendered, and "switch between light and dark"
 * describes the control accurately in either state.
 */
export function ThemeToggle({ className }: { className?: string }) {
  return (
    <button
      type="button"
      aria-label="Switch between the light and dark theme"
      title="Switch theme"
      onClick={() => {
        const root = document.documentElement;
        const next = root.dataset.theme === "light" ? "dark" : "light";
        root.dataset.theme = next;
        try {
          localStorage.setItem("theme", next);
        } catch {
          // Private mode, or storage disabled. The theme still switches for
          // this page; it just will not be remembered. Not worth an error.
        }
      }}
      className={cn(
        "relative inline-flex h-8 w-8 items-center justify-center rounded-lg",
        "border border-line bg-glass-2 text-muted shadow-hairline",
        "transition-colors duration-200 hover:border-line-strong hover:bg-glass-3 hover:text-ink",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-void",
        className,
      )}
    >
      <Sun aria-hidden="true" className="block h-4 w-4 light:hidden" />
      <Moon aria-hidden="true" className="hidden h-4 w-4 light:block" />
    </button>
  );
}
