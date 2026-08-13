"use client";

import { useQuery } from "@tanstack/react-query";
import { buttonClasses } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { API_BASE, api } from "@/lib/api";

/**
 * Hands the browser to the backend, which drives the whole OIDC handshake.
 *
 * A plain `<a>`, not a fetch: this is a **top-level navigation** to Google's
 * consent screen and back. An XHR cannot follow that, and the `state`/PKCE
 * cookie the backend sets on the redirect only rides along on a real
 * navigation.
 *
 * The v1 project needed a `/auth/callback` page here to finish the job,
 * because its callback set only the refresh cookie and the client had to
 * exchange it. Ours sets both cookies on the redirect itself, so the browser
 * arrives at the destination already signed in and there is no interstitial to
 * build — or to leak an error through.
 *
 * Hidden entirely when the backend has no client configured: a button that
 * leads to a Google error page is worse than no button.
 *
 * Note the `<a>` carries the button styling itself rather than wrapping a
 * `<button>`: an anchor around a button is invalid HTML and announces as two
 * nested controls.
 */
export function GoogleButton({ next = "/dashboard" }: { next?: string }) {
  const status = useQuery({
    queryKey: ["google-enabled"],
    queryFn: () => api<{ enabled: boolean; hint?: string }>("/auth/google/status"),
    retry: false,
    staleTime: Infinity,
  });

  if (!status.data?.enabled) {
    // The hint only exists outside production, so this renders for whoever is
    // running the app and never for a real user.
    return status.data?.hint ? (
      <Notice role="status" className="text-xs">
        <strong className="font-semibold text-ink">Google sign-in is off.</strong>{" "}
        {status.data.hint}
      </Notice>
    ) : null;
  }

  const href = `${API_BASE}/api/v1/auth/google/login?next=${encodeURIComponent(next)}`;

  return (
    <div className="space-y-4">
      <a href={href} className={buttonClasses({ variant: "secondary", size: "lg", className: "w-full" })}>
        <span className="relative z-10 inline-flex items-center gap-2.5">
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path
              fill="#EA4335"
              d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
            />
            <path
              fill="#4285F4"
              d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
            />
            <path
              fill="#FBBC05"
              d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
            />
            <path
              fill="#34A853"
              d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
            />
          </svg>
          Continue with Google
        </span>
      </a>

      <div className="flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-gradient-to-r from-transparent to-line" />
        <span className="text-xs text-faint">or use an email and password</span>
        <span className="h-px flex-1 bg-gradient-to-l from-transparent to-line" />
      </div>
    </div>
  );
}
