"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { User } from "@/lib/types";

/**
 * Primary nav, and the only place the app says who you are.
 *
 * Registering already signs you in — the API sets HttpOnly cookies on
 * `/auth/register` exactly as it does on `/auth/login`. But nothing on screen
 * said so, which made a working session look like a broken one. Signed-in
 * state has to be *visible*, or "am I logged in?" is a question the user has to
 * answer by experiment.
 *
 * The token never touches JavaScript, so identity is a request: ask
 * `/auth/me`. A 401 is the answer "nobody", not an error to shout about.
 */
export function NavBar() {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    retry: false, // a 401 is a fact, not a flake
    staleTime: 60_000,
  });

  const signOut = useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      // Drop every cached answer, not just identity: the session list and any
      // report in memory belong to the person who just left.
      queryClient.clear();
      router.push("/");
    },
  });

  const signedIn = me.isSuccess && !!me.data;
  const unauthenticated = (me.error as ApiError | null)?.status === 401;

  return (
    <header className="sticky top-0 z-40 border-b border-line-soft bg-void/70 backdrop-blur-xl">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-5 sm:px-6"
      >
        <Link
          href="/"
          className="group flex shrink-0 items-center gap-2.5 rounded-lg text-[0.9375rem] font-semibold tracking-tight text-ink"
        >
          <span
            aria-hidden="true"
            className="relative flex h-7 w-7 items-center justify-center overflow-hidden rounded-lg bg-gradient-to-br from-accent-soft via-accent to-accent-deep shadow-[0_0_18px_-4px_rgba(139,92,246,0.9)]"
          >
            <span className="absolute inset-px rounded-[7px] bg-void/85" />
            <svg
              viewBox="0 0 16 16"
              className="relative h-3.5 w-3.5 text-accent-soft"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 9.5 6.5 13 13 3.5" />
            </svg>
          </span>
          <span className="hidden sm:inline">Interview practice</span>
          <span className="sm:hidden">Practice</span>
        </Link>

        {signedIn && (
          <div className="ml-2 flex items-center gap-1">
            <NavLink href="/dashboard" active={pathname === "/dashboard"}>
              My interviews
            </NavLink>
            <NavLink href="/practice" active={pathname === "/practice"}>
              Start a session
            </NavLink>
          </div>
        )}

        <div className="ml-auto flex items-center gap-3">
          {/* Outside both branches: the theme is not an account setting, and
              it has to be reachable on the signed-out landing page too. */}
          <ThemeToggle />
          {signedIn && (
            <>
              <span className="hidden text-xs text-muted lg:inline">
                Signed in as{" "}
                <strong className="font-medium text-ink">
                  {me.data.display_name || me.data.email}
                </strong>
              </span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={signOut.isPending}
                onClick={() => signOut.mutate()}
              >
                {signOut.isPending ? "Signing out…" : "Sign out"}
              </Button>
            </>
          )}
          {unauthenticated && (
            <>
              <NavLink href="/login" active={pathname === "/login"}>
                Sign in
              </NavLink>
              <Link
                href="/practice"
                className="hidden rounded-xl bg-gradient-to-r from-accent-deep to-accent px-3.5 py-1.5 text-[0.8125rem] font-medium text-white shadow-[0_8px_24px_-12px_rgba(139,92,246,1)] transition hover:brightness-110 sm:inline-block"
              >
                Start practising
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}

/** A nav item whose current-page state is a pill, an underline, and `aria-current`. */
function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative rounded-lg px-3 py-1.5 text-[0.8125rem] transition-colors duration-200",
        active ? "text-ink" : "text-muted hover:text-ink",
      )}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-lg border border-line bg-glass-2"
        />
      )}
      <span className="relative">{children}</span>
    </Link>
  );
}
