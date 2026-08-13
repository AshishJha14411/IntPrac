"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { GradientCard } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/feedback";
import { Hint, Input, Label } from "@/components/ui/field";
import { Segmented } from "@/components/ui/segmented";
import { ApiError, api } from "@/lib/api";
import { GoogleButton } from "./GoogleButton";

type Mode = "login" | "register";

/** The OAuth callback bounces here with a reason when it could not finish. */
const OAUTH_ERRORS: Record<string, string> = {
  cancelled: "Google sign-in was cancelled. Nothing was changed.",
  failed:
    "Google sign-in could not be completed. Try again, or use an email and password instead.",
};

const MODES = [
  { value: "login" as const, label: "Sign in" },
  { value: "register" as const, label: "Create account" },
];

/**
 * Client island: the interactive part of an otherwise static page.
 *
 * Tokens are set as HttpOnly cookies by the API, so nothing here ever touches
 * a token — which is the point.
 */
export function AuthForm() {
  const router = useRouter();
  const oauthError = OAUTH_ERRORS[useSearchParams().get("error") ?? ""];
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const submit = useMutation({
    mutationFn: async () =>
      mode === "login"
        ? api("/auth/login", { method: "POST", body: { email, password } })
        : api("/auth/register", {
            method: "POST",
            body: { email, password, display_name: displayName || email.split("@")[0] },
          }),
    onSuccess: () => router.push("/practice"),
  });

  const error = submit.error as ApiError | null;

  return (
    <GradientCard>
      <form
        className="space-y-5 p-6 sm:p-7"
        onSubmit={(event) => {
          event.preventDefault();
          submit.mutate();
        }}
      >
        <Segmented
          options={MODES}
          value={mode}
          onChange={setMode}
          ariaLabel="Sign in or create an account"
        />

        {oauthError && <ErrorNote role="alert">{oauthError}</ErrorNote>}

        <GoogleButton />

        {error && (
          <ErrorNote role="alert">
            {error.message}
            {error.problem?.request_id && (
              <span className="ml-1 font-mono text-xs opacity-70">
                ({error.problem.request_id})
              </span>
            )}
          </ErrorNote>
        )}

        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        {mode === "register" && (
          <div>
            <Label htmlFor="name">Display name</Label>
            <Input
              id="name"
              autoComplete="name"
              placeholder="Optional"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>
        )}

        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? 12 : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby={mode === "register" ? "pw-help" : undefined}
          />
          {mode === "register" && (
            <Hint id="pw-help">
              At least 12 characters. Length is what actually matters — a passphrase beats
              punctuation.
            </Hint>
          )}
        </div>

        <Button type="submit" size="lg" disabled={submit.isPending} className="w-full">
          {submit.isPending ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
    </GradientCard>
  );
}
