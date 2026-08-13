import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * The one-line helper every Aceternity component assumes exists.
 *
 * `clsx` flattens conditionals; `twMerge` then resolves Tailwind conflicts by
 * last-wins, which is what makes a `className` prop able to override a
 * component's own padding or colour instead of silently losing to it.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
