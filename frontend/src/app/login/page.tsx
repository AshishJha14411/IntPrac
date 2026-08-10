import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "./AuthForm";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="shell" style={{ maxWidth: 460 }}>
      <h1>Sign in</h1>
      {/* The form reads `?error=` from the OAuth callback via
          `useSearchParams`, which cannot be known at build time. Without a
          boundary here the whole page opts out of static rendering; with one,
          only the form waits for the client. */}
      <Suspense fallback={<div className="card">Loading…</div>}>
        <AuthForm />
      </Suspense>
    </div>
  );
}
