import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Form controls.
 *
 * Tailwind's preflight strips the browser's own field styling, so these are
 * not decoration on top of a working control — they *are* the control's
 * appearance, and the states that matter (focus, invalid, disabled, file
 * picker) all have to be spelled out rather than inherited.
 *
 * Every one of them keeps a real focus ring. The Aceternity look uses a soft
 * violet glow, which is pretty but not a focus indicator, so the ring is
 * present in addition to it.
 */

const CONTROL = cn(
  "w-full rounded-xl border border-line bg-glass-2 px-3.5 py-2.5",
  "text-sm text-ink placeholder:text-faint",
  "shadow-input",
  "transition-[border-color,box-shadow,background-color] duration-200",
  "hover:border-line-strong",
  "focus:outline-none focus-visible:border-accent/70 focus-visible:bg-glass-3",
  "focus-visible:ring-2 focus-visible:ring-accent/45",
  "disabled:cursor-not-allowed disabled:opacity-50",
);

export function Label({ children, className, ...rest }: React.ComponentPropsWithRef<"label">) {
  return (
    <label
      className={cn("mb-2 block text-sm font-medium tracking-tight text-ink", className)}
      {...rest}
    >
      {children}
    </label>
  );
}

export function Input({ className, ...rest }: React.ComponentPropsWithRef<"input">) {
  return (
    <input
      className={cn(
        CONTROL,
        // The file picker is a shadow-DOM button; it needs its own styling or
        // it renders as a bare system control in the middle of the form.
        "file:mr-3 file:rounded-lg file:border-0 file:bg-accent/20 file:px-3 file:py-1.5",
        "file:text-xs file:font-medium file:text-accent-soft hover:file:bg-accent/30",
        className,
      )}
      {...rest}
    />
  );
}

export function Textarea({ className, ...rest }: React.ComponentPropsWithRef<"textarea">) {
  return (
    <textarea className={cn(CONTROL, "min-h-40 resize-y leading-relaxed", className)} {...rest} />
  );
}

export function Select({ className, children, ...rest }: React.ComponentPropsWithRef<"select">) {
  return (
    <div className="relative">
      <select
        className={cn(
          CONTROL,
          "cursor-pointer appearance-none pr-10",
          // The popup itself is drawn by the OS, so its options need an
          // explicit dark background or they land as black-on-white.
          "[&>option]:bg-raised [&>option]:text-ink",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        className="pointer-events-none absolute top-1/2 right-3.5 h-4 w-4 -translate-y-1/2 text-faint"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="m5 7.5 5 5 5-5" />
      </svg>
    </div>
  );
}

/** A checkbox and its wording, as one target. Native input, styled — not a div pretending. */
export function CheckField({
  checked,
  onChange,
  disabled,
  children,
  className,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label
      className={cn(
        "group flex cursor-pointer items-start gap-3 rounded-xl border border-line-soft bg-glass-2 p-3",
        "transition-colors duration-200 hover:border-line-strong hover:bg-glass-3",
        "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60",
        checked && "border-accent/45 bg-accent/[0.07]",
        className,
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className={cn(
          "mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-line-strong bg-glass-3 accent-accent",
          "focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-void",
        )}
      />
      <span className="text-sm leading-relaxed text-ink/90">{children}</span>
    </label>
  );
}

export function Hint({ children, className, ...rest }: React.ComponentPropsWithRef<"p">) {
  return (
    <p className={cn("mt-2 text-xs leading-relaxed text-muted", className)} {...rest}>
      {children}
    </p>
  );
}
