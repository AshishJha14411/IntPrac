"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ProgressPoint, SessionPage, SessionSummary } from "@/lib/types";

/**
 * "How have my interviews been?" — the question the app could not answer.
 *
 * Both halves already existed on the API and had nothing rendering them:
 * `GET /sessions` is keyset-paginated history, and `GET /reports/me/progress`
 * is FR-F4's read model, which computes the delta against your previous score
 * with a `LAG` window function in the database rather than diffing in
 * JavaScript.
 *
 * Practice without a visible arc is just repetition, so the trend leads and the
 * list follows.
 */

/** Statuses where the interview is still yours to finish. */
const RESUMABLE = new Set(["planned", "consent_pending", "device_check", "in_progress"]);
/** Statuses where a report exists to read. */
const REPORTABLE = new Set(["completed", "graded", "published", "reviewed"]);

export function Dashboard() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [confirming, setConfirming] = useState<string | null>(null);

  /**
   * G-009: the deletion the consent screen promises.
   *
   * Two-step, and deliberately not a `window.confirm`: a native dialog is not
   * styleable, not translatable, and is exactly what people click through.
   * Naming the consequence in the button beats an "Are you sure?".
   */
  const remove = useMutation({
    mutationFn: (id: string) => api(`/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setConfirming(null);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["progress"] });
    },
  });

  const closeAccount = useMutation({
    mutationFn: () => api("/auth/me", { method: "DELETE" }),
    onSuccess: () => {
      queryClient.clear();
      router.push("/");
    },
  });

  const progress = useQuery({
    queryKey: ["progress"],
    // `/me/progress`, not `/reports/...`: the reports router carries no prefix,
    // so the report itself lives at `/sessions/{id}/report` and this one hangs
    // off the current user. Worth a look next to `router.py` before editing.
    queryFn: () => api<{ series: ProgressPoint[] }>("/me/progress"),
    retry: false,
  });

  // Keyset, not offset: the cursor is `(created_at, id)`, so a session finished
  // while you are reading page one cannot shuffle a row onto page two.
  const history = useInfiniteQuery({
    queryKey: ["sessions"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<SessionPage>(`/sessions${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`),
    getNextPageParam: (last) => last.next_cursor,
    retry: false,
  });

  const authError = [progress.error, history.error].find(
    (error) => (error as ApiError | null)?.status === 401,
  );
  if (authError) {
    return (
      <p className="notice" role="status">
        <Link href="/login">Sign in</Link> to see your interviews.
      </p>
    );
  }

  const sessions = history.data?.pages.flatMap((page) => page.items) ?? [];
  const series = progress.data?.series ?? [];

  return (
    <>
      <TrendSection series={series} loading={progress.isLoading} />
      <HistorySection
        sessions={sessions}
        loading={history.isLoading}
        hasMore={!!history.hasNextPage}
        loadingMore={history.isFetchingNextPage}
        onLoadMore={() => history.fetchNextPage()}
        confirming={confirming}
        onConfirm={setConfirming}
        onDelete={(id) => remove.mutate(id)}
        deleting={remove.isPending}
      />
      <DangerZone
        onClose={() => closeAccount.mutate()}
        pending={closeAccount.isPending}
      />
    </>
  );
}

function TrendSection({ series, loading }: { series: ProgressPoint[]; loading: boolean }) {
  if (loading) return <p className="muted">Loading your trend…</p>;
  if (series.length === 0) {
    return (
      <div className="notice" role="status">
        <strong>No graded interviews yet.</strong> Finish one and this fills in — you&rsquo;ll see
        each competency&rsquo;s score and whether it moved since last time.
      </div>
    );
  }

  // One row per competency, keeping the most recent point. The series arrives
  // ordered by completion, so the last occurrence is the current standing.
  const latest = new Map<string, ProgressPoint>();
  for (const point of series) latest.set(point.competency_id, point);
  const rows = [...latest.values()].sort((a, b) => a.score - b.score);

  // Session-level average, so "am I getting better overall?" has an answer that
  // isn't 14 separate bars.
  const bySession = new Map<string, { at: string | null; scores: number[] }>();
  for (const point of series) {
    const entry = bySession.get(point.session_id) ?? { at: point.completed_at, scores: [] };
    entry.scores.push(point.score);
    bySession.set(point.session_id, entry);
  }
  const overall = [...bySession.entries()].map(([id, entry]) => ({
    id,
    at: entry.at,
    score: entry.scores.reduce((sum, value) => sum + value, 0) / entry.scores.length,
  }));

  return (
    <section>
      <h2>How you&rsquo;re trending</h2>

      {overall.length > 1 && (
        <div className="card">
          <p className="small muted" style={{ marginTop: 0 }}>
            Overall score per interview, oldest first.
          </p>
          <div className="row" style={{ alignItems: "flex-end", gap: 8, minHeight: 90 }}>
            {overall.map((point) => (
              <div key={point.id} style={{ textAlign: "center", flex: "0 0 44px" }}>
                <div
                  title={`${pct(point.score)} on ${formatDate(point.at)}`}
                  style={{
                    height: Math.max(4, Math.round(point.score * 72)),
                    background: "currentColor",
                    opacity: 0.75,
                    borderRadius: 3,
                  }}
                />
                <span className="small muted mono">{pct(point.score)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card stack">
        <p className="small muted" style={{ margin: 0 }}>
          Weakest first — that ordering is the point of the page.
        </p>
        {rows.map((row) => (
          <div key={row.competency_id}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
              <code className="small">{row.competency_id}</code>
              <span className="small mono">
                {pct(row.score)} <DeltaLabel delta={row.delta} />
              </span>
            </div>
            <div
              className="meter"
              role="progressbar"
              aria-valuenow={Math.round(row.score * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${row.competency_id} score`}
              style={{ marginTop: 4 }}
            >
              <span style={{ width: `${Math.round(row.score * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function HistorySection({
  sessions,
  loading,
  hasMore,
  loadingMore,
  onLoadMore,
  confirming,
  onConfirm,
  onDelete,
  deleting,
}: {
  sessions: SessionSummary[];
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  confirming: string | null;
  onConfirm: (id: string | null) => void;
  onDelete: (id: string) => void;
  deleting: boolean;
}) {
  return (
    <section>
      <h2>Your interviews</h2>
      {loading && <p className="muted">Loading…</p>}
      {!loading && sessions.length === 0 && (
        <div className="card">
          <p style={{ marginTop: 0 }}>Nothing here yet.</p>
          <Link href="/practice">
            <button>Start your first session</button>
          </Link>
        </div>
      )}

      <div className="stack">
        {sessions.map((session) => (
          <div
            className="card row"
            key={session.id}
            style={{ justifyContent: "space-between", alignItems: "center", gap: 16 }}
          >
            <div>
              <div className="row small" style={{ gap: 10 }}>
                <strong>{formatDate(session.completed_at ?? session.created_at)}</strong>
                <span className="muted">
                  {session.mode} · {session.seniority} · {session.question_count} questions
                </span>
              </div>
              <span className="small muted">{describeStatus(session.status)}</span>
            </div>
            {RESUMABLE.has(session.status) && (
              <Link href={`/interview/${session.id}`}>
                <button>Continue</button>
              </Link>
            )}
            {REPORTABLE.has(session.status) && (
              <Link href={`/report/${session.id}`}>
                <button className="secondary">Open report</button>
              </Link>
            )}
            {confirming === session.id ? (
              <span className="row small" style={{ gap: 8 }}>
                <button
                  className="secondary"
                  disabled={deleting}
                  onClick={() => onDelete(session.id)}
                >
                  {deleting ? "Deleting…" : "Delete permanently"}
                </button>
                <button className="secondary" onClick={() => onConfirm(null)}>
                  Keep
                </button>
              </span>
            ) : (
              <button
                className="secondary"
                aria-label={`Delete the interview from ${formatDate(session.created_at)}`}
                onClick={() => onConfirm(session.id)}
              >
                Delete
              </button>
            )}
          </div>
        ))}
      </div>

      {hasMore && (
        <button className="secondary" disabled={loadingMore} onClick={onLoadMore}>
          {loadingMore ? "Loading…" : "Load older"}
        </button>
      )}
    </section>
  );
}

/**
 * Direction is stated in words as well as an arrow.
 *
 * NFR-A: never colour or glyph alone. A screen reader announcing "up 6 points"
 * is the same information a sighted user gets from the triangle.
 */
function DeltaLabel({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="muted"> · first time</span>;
  if (Math.abs(delta) < 0.005) return <span className="muted"> · no change</span>;
  const up = delta > 0;
  return (
    <span className="muted">
      {" "}
      · {up ? "▲" : "▼"} {up ? "up" : "down"} {Math.abs(Math.round(delta * 100))} pts
    </span>
  );
}

const pct = (score: number) => `${Math.round(score * 100)}%`;

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function describeStatus(status: string): string {
  if (RESUMABLE.has(status)) return "In progress — pick up where you left off";
  if (status === "abandoned") return "Abandoned";
  if (status === "completed") return "Grading…";
  return "Graded";
}

/**
 * Account deletion (G-009).
 *
 * Kept visually separate and last, because it is irreversible and nobody
 * should reach it while looking for something else. Two clicks, and the
 * second one says what it does rather than "OK".
 */
function DangerZone({ onClose, pending }: { onClose: () => void; pending: boolean }) {
  const [armed, setArmed] = useState(false);
  return (
    <section>
      <h2>Your data</h2>
      <div className="card stack">
        <p className="small muted" style={{ margin: 0 }}>
          Everything here is kept for up to <strong>6 months</strong> and then deleted
          automatically — transcripts included, not just uploaded files. You can delete any single
          interview above, or remove the account entirely.
        </p>
        {armed ? (
          <div className="row">
            <button className="secondary" disabled={pending} onClick={onClose}>
              {pending ? "Deleting…" : "Yes, delete my account and every interview"}
            </button>
            <button className="secondary" onClick={() => setArmed(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button className="secondary" onClick={() => setArmed(true)}>
            Delete my account
          </button>
        )}
      </div>
    </section>
  );
}
