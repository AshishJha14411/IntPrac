"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
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
    <nav className="row" aria-label="Primary" style={{ alignItems: "baseline" }}>
      <Link href="/" style={{ fontWeight: 700, textDecoration: "none" }}>
        Interview practice
      </Link>

      {signedIn && (
        <span className="row small" style={{ gap: 14, marginLeft: 18 }}>
          <Link href="/dashboard" aria-current={pathname === "/dashboard" ? "page" : undefined}>
            My interviews
          </Link>
          <Link href="/practice" aria-current={pathname === "/practice" ? "page" : undefined}>
            Start a session
          </Link>
        </span>
      )}

      <span className="row small muted" style={{ marginLeft: "auto", gap: 12 }}>
        {signedIn && (
          <>
            <span>
              Signed in as <strong>{me.data.display_name || me.data.email}</strong>
            </span>
            <button
              type="button"
              className="secondary"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              {signOut.isPending ? "Signing out…" : "Sign out"}
            </button>
          </>
        )}
        {unauthenticated && <Link href="/login">Sign in</Link>}
      </span>
    </nav>
  );
}
