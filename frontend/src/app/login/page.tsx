import type { Metadata } from "next";
import { Suspense } from "react";
import { Aurora, GridGround } from "@/components/ui/backgrounds";
import { Card } from "@/components/ui/card";
import { Shell } from "@/components/ui/shell";
import { AuthForm } from "./AuthForm";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="relative isolate">
      <Aurora className="h-[36rem]" />
      <GridGround className="h-[36rem]" />
      <Shell width="tight" className="relative pt-16">
        <h1 className="text-gradient mb-2 text-center text-3xl font-semibold tracking-tight">
          Welcome back
        </h1>
        <p className="mb-8 text-center text-sm text-muted">
          One account, every session you&rsquo;ve taken.
        </p>
        {/* The form reads `?error=` from the OAuth callback via
            `useSearchParams`, which cannot be known at build time. Without a
            boundary here the whole page opts out of static rendering; with one,
            only the form waits for the client. */}
        <Suspense
          fallback={
            <Card className="p-6 text-sm text-muted">
              <span className="animate-pulse">Loading…</span>
            </Card>
          }
        >
          <AuthForm />
        </Suspense>
      </Shell>
    </div>
  );
}
