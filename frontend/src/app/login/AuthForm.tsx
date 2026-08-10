"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { GoogleButton } from "./GoogleButton";

type Mode = "login" | "register";

/** The OAuth callback bounces here with a reason when it could not finish. */
const OAUTH_ERRORS: Record<string, string> = {
  cancelled: "Google sign-in was cancelled. Nothing was changed.",
  failed:
    "Google sign-in could not be completed. Try again, or use an email and password instead.",
};

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
    <form
      className="card stack"
      onSubmit={(event) => {
        event.preventDefault();
        submit.mutate();
      }}
    >
      <div className="row" role="tablist" aria-label="Sign in or create an account">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "login"}
          className={mode === "login" ? "" : "secondary"}
          onClick={() => setMode("login")}
        >
          Sign in
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "register"}
          className={mode === "register" ? "" : "secondary"}
          onClick={() => setMode("register")}
        >
          Create account
        </button>
      </div>

      {oauthError && (
        <p className="error" role="alert">
          {oauthError}
        </p>
      )}

      <GoogleButton />

      {error && (
        <p className="error" role="alert">
          {error.message}
          {error.problem?.request_id && (
            <span className="small muted mono"> ({error.problem.request_id})</span>
          )}
        </p>
      )}

      <div>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>

      {mode === "register" && (
        <div>
          <label htmlFor="name">Display name</label>
          <input
            id="name"
            autoComplete="name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>
      )}

      <div>
        <label htmlFor="password">Password</label>
        <input
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
          <p id="pw-help" className="small muted" style={{ margin: "6px 0 0" }}>
            At least 12 characters. Length is what actually matters — a passphrase beats
            punctuation.
          </p>
        )}
      </div>

      <button type="submit" disabled={submit.isPending}>
        {submit.isPending ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
      </button>
    </form>
  );
}
