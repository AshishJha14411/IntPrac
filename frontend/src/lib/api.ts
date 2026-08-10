/**
 * The API client.
 *
 * Every error path funnels through `ApiError`, which carries the problem+json
 * body -- so the UI branches on a stable `type`/`status` rather than matching
 * on a message string that a copy edit could break.
 *
 * Auth uses HttpOnly cookies, so `credentials: "include"` is mandatory on every
 * request and the token never touches JavaScript.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

/** Server components talk to the API over the compose network. */
export const INTERNAL_API_BASE =
  process.env.INTERNAL_API_BASE_URL ?? API_BASE;

const PREFIX = "/api/v1";

export type Problem = {
  type: string;
  title: string;
  status: number;
  detail: string;
  request_id?: string;
  errors?: unknown[];
};

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.detail ?? fallback);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }

  get code(): string {
    return this.problem?.type.split("/").pop() ?? "unknown";
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /** Server components must forward the incoming cookie header themselves. */
  cookie?: string;
  base?: string;
  cache?: RequestCache;
};

/**
 * In-flight refresh, shared by every caller.
 *
 * Without this, a page with four queries that all 401 at once fires four
 * refreshes. The server rotates the refresh token on each one, so the second
 * arrives holding a token the first already rotated — which is precisely what
 * reuse detection is built to punish, and it revokes the **whole family**. The
 * user is then hard-logged-out by their own client. One shared promise means
 * one rotation.
 */
let refreshing: Promise<boolean> | null = null;

/** Endpoints where a 401 is the answer, not a stale token. */
const NEVER_RENEW = new Set([
  "/auth/login",
  "/auth/register",
  "/auth/refresh",
  "/auth/logout",
]);

function refreshSession(base: string): Promise<boolean> {
  refreshing ??= fetch(`${base}${PREFIX}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, cookie, base = API_BASE, cache = "no-store" } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (cookie) headers["Cookie"] = cookie;

  const send = () =>
    fetch(`${base}${PREFIX}${path}`, {
      method,
      headers,
      credentials: "include",
      cache,
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  let response = await send();

  // The access cookie lives 15 minutes; the refresh cookie lives 30 days. With
  // nothing spending the second, an interview longer than the first ended with
  // the candidate silently logged out mid-answer. Renew once, then retry.
  //
  // A deny list, not `startsWith("/auth/")`: `/auth/me` is exactly the call
  // that must renew, or the nav reports "signed out" while every other page
  // quietly refreshes and keeps working. What must *not* renew is the handful
  // of endpoints where a 401 is the real answer — a failed login has to stay a
  // failed login, and refreshing on /auth/refresh would recurse.
  const renewable =
    response.status === 401 && !cookie && !NEVER_RENEW.has(path.split("?")[0] ?? path);
  if (renewable && (await refreshSession(base))) {
    response = await send();
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const parsed: unknown = text ? safeParse(text) : null;

  if (!response.ok) {
    throw new ApiError(
      response.status,
      isProblem(parsed) ? parsed : null,
      `Request failed with ${response.status}`,
    );
  }
  return parsed as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    "title" in value &&
    "status" in value &&
    "detail" in value
  );
}

/** A stable per-attempt key, so a retry is recognised as the same submission. */
export function newIdempotencyKey(): string {
  return `ans-${crypto.randomUUID()}`;
}
