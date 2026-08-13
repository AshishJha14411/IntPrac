"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/button";
import { Card, GlowCard } from "@/components/ui/card";
import { Badge, Meter, Notice, SectionHeading } from "@/components/ui/feedback";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
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
      <Notice role="status" tone="accent">
        <Link href="/login" className="font-semibold text-accent-soft underline underline-offset-4">
          Sign in
        </Link>{" "}
        to see your interviews.
      </Notice>
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
      <DangerZone onClose={() => closeAccount.mutate()} pending={closeAccount.isPending} />
    </>
  );
}

function TrendSection({ series, loading }: { series: ProgressPoint[]; loading: boolean }) {
  if (loading) return <p className="text-sm text-muted">Loading your trend…</p>;
  if (series.length === 0) {
    return (
      <Notice role="status" tone="accent" className="p-5">
        <strong className="font-semibold text-ink">No graded interviews yet.</strong> Finish one
        and this fills in — you&rsquo;ll see each competency&rsquo;s score and whether it moved
        since last time.
      </Notice>
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
      <SectionHeading hint="Weakest first — that ordering is the point of the page.">
        How you&rsquo;re trending
      </SectionHeading>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        {overall.length > 1 && (
          <GlowCard className="p-6">
            <div className="mb-5 flex items-center gap-2 text-xs tracking-wide text-faint uppercase">
              <TrendingUp aria-hidden="true" className="h-3.5 w-3.5" />
              Overall per interview, oldest first
            </div>
            <div className="flex min-h-28 flex-wrap items-end gap-3">
              {overall.map((point) => (
                <div key={point.id} className="group/bar flex w-11 flex-col items-center gap-1.5">
                  <div
                    title={`${pct(point.score)} on ${formatDate(point.at)}`}
                    style={{ height: Math.max(6, Math.round(point.score * 84)) }}
                    className={cn(
                      "w-full rounded-md bg-gradient-to-t from-accent-deep to-accent-cool",
                      "shadow-[0_0_18px_-6px_rgba(139,92,246,0.9)]",
                      "transition-all duration-300 group-hover/bar:brightness-125",
                    )}
                  />
                  <span className="font-mono text-[0.7rem] text-faint">{pct(point.score)}</span>
                </div>
              ))}
            </div>
          </GlowCard>
        )}

        <Card className="p-6">
          <div className="space-y-4">
            {rows.map((row) => (
              <div key={row.competency_id}>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <code className="truncate font-mono text-xs text-accent-soft">
                    {row.competency_id}
                  </code>
                  <span className="shrink-0 font-mono text-xs text-ink">
                    {pct(row.score)} <DeltaLabel delta={row.delta} />
                  </span>
                </div>
                <Meter
                  percent={row.score * 100}
                  valueNow={Math.round(row.score * 100)}
                  ariaLabel={`${row.competency_id} score`}
                />
              </div>
            ))}
          </div>
        </Card>
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
      <SectionHeading>Your interviews</SectionHeading>

      {loading && <p className="text-sm text-muted">Loading…</p>}
      {!loading && sessions.length === 0 && (
        <Card className="flex flex-col items-start gap-4 p-8">
          <p className="text-sm text-muted">Nothing here yet.</p>
          <LinkButton href="/practice">Start your first session</LinkButton>
        </Card>
      )}

      <div className="space-y-3">
        {sessions.map((session) => (
          <GlowCard key={session.id} className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2.5">
                  <strong className="text-sm font-semibold text-ink">
                    {formatDate(session.completed_at ?? session.created_at)}
                  </strong>
                  <Badge>{session.mode}</Badge>
                  <Badge>{session.seniority}</Badge>
                  <Badge>{session.question_count} questions</Badge>
                </div>
                <span className="mt-1.5 block text-xs text-muted">
                  {describeStatus(session.status)}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {RESUMABLE.has(session.status) && (
                  <LinkButton href={`/interview/${session.id}`} size="sm">
                    Continue
                  </LinkButton>
                )}
                {REPORTABLE.has(session.status) && (
                  <LinkButton href={`/report/${session.id}`} variant="secondary" size="sm">
                    Open report
                  </LinkButton>
                )}
                {confirming === session.id ? (
                  <>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={deleting}
                      onClick={() => onDelete(session.id)}
                    >
                      {deleting ? "Deleting…" : "Delete permanently"}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => onConfirm(null)}>
                      Keep
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete the interview from ${formatDate(session.created_at)}`}
                    onClick={() => onConfirm(session.id)}
                  >
                    <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
                    Delete
                  </Button>
                )}
              </div>
            </div>
          </GlowCard>
        ))}
      </div>

      {hasMore && (
        <Button variant="secondary" className="mt-4" disabled={loadingMore} onClick={onLoadMore}>
          {loadingMore ? "Loading…" : "Load older"}
        </Button>
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
  if (delta === null) return <span className="text-faint"> · first time</span>;
  if (Math.abs(delta) < 0.005) return <span className="text-faint"> · no change</span>;
  const up = delta > 0;
  return (
    <span className={up ? "text-covered" : "text-missed"}>
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
      <SectionHeading>Your data</SectionHeading>
      <Card className="border-missed/20 bg-missed/[0.03] p-6">
        <p className="text-sm leading-relaxed text-muted">
          Everything here is kept for up to{" "}
          <strong className="font-medium text-ink">6 months</strong> and then deleted
          automatically — transcripts included, not just uploaded files. You can delete any single
          interview above, or remove the account entirely.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          {armed ? (
            <>
              <Button variant="danger" disabled={pending} onClick={onClose}>
                {pending ? "Deleting…" : "Yes, delete my account and every interview"}
              </Button>
              <Button variant="ghost" onClick={() => setArmed(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setArmed(true)}>
              Delete my account
            </Button>
          )}
        </div>
      </Card>
    </section>
  );
}
