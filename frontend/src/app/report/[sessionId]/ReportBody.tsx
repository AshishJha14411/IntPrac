import { Card, GlowCard, GradientCard } from "@/components/ui/card";
import {
  Badge,
  Meter,
  Notice,
  SectionHeading,
  VerdictChip,
  verdictBar,
} from "@/components/ui/feedback";
import { Shell } from "@/components/ui/shell";
import { cn } from "@/lib/cn";
import type { ConceptLine, SessionReport } from "@/lib/types";
import { RefreshWhilePending } from "./RefreshWhilePending";

/**
 * The report body, shared by the server render and the client fallback.
 *
 * Its own module, and a component rather than a function, for a reason that
 * cost a production error page. It used to live in the page and be handed to
 * `ClientReport` as a render prop:
 *
 *     <ClientReport sessionId={id}>{(data) => renderReport(data)}</ClientReport>
 *
 * A function cannot cross the Server → Client Component boundary. React has to
 * serialise every prop a Server Component passes to a Client one, and a
 * closure has no serialisation, so React replaced `children` with an Error.
 * The fallback written to rescue the split-domain 401 was itself the thing
 * that failed, and the user saw "Something went wrong" with a digest.
 *
 * Neither `tsc` nor `next build` catches this -- the prop type is valid React
 * and the failure only exists at render time, on the server, in production.
 * It never appeared locally because same-origin dev forwards the cookie, so
 * the 401 branch that reaches this code never ran.
 *
 * Importing the component from both sides has no such boundary problem: each
 * side renders it in its own environment, and there is still exactly one copy
 * of the markup.
 */
export function ReportBody({ report }: { report: SessionReport }) {
  const pct = (value: number) => `${Math.round(value * 100)}%`;

  return (
    <Shell width="wide">
      <header className="relative isolate mb-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-28 left-1/3 -z-10 h-64 w-[30rem] rounded-full bg-bloom-1 blur-[120px]"
        />
        <h1 className="text-gradient text-3xl font-semibold tracking-tight sm:text-4xl">
          Your report
        </h1>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge>{report.mode} mode</Badge>
          <Badge>{report.seniority} level</Badge>
          <Badge>
            {report.graded_questions} of {report.graded_questions + report.pending_questions}{" "}
            questions graded
          </Badge>
        </div>
      </header>

      {report.pending_questions > 0 && (
        <>
          <Notice role="status" tone="accent" className="mb-6">
            <span className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-soft"
              />
              {report.pending_questions} answer(s) are still being graded. Grading runs after the
              session so it never slows the interview down.
            </span>
          </Notice>
          <RefreshWhilePending />
        </>
      )}

      {/* ── overall ───────────────────────────────────────────────────── */}
      <GradientCard>
        <div className="p-7 sm:p-8">
          <p className="text-xs tracking-[0.18em] text-faint uppercase">Overall</p>
          <p className="text-gradient-accent mt-2 text-3xl font-semibold tracking-tight capitalize sm:text-4xl">
            {report.recommendation}
          </p>

          <dl className="mt-6 grid gap-5 sm:grid-cols-2">
            <ScoreReadout label="Raw" value={report.overall_raw} format={pct} />
            <ScoreReadout
              label="After accounting for hints"
              value={report.overall_hint_adjusted}
              format={pct}
            />
          </dl>

          <p className="mt-5 text-xs leading-relaxed text-faint">
            Both are shown because hiding either would be dishonest: one hides the help, the other
            hides the penalty.
          </p>
        </div>
      </GradientCard>

      {/* ── per competency ────────────────────────────────────────────── */}
      {report.competencies.length > 0 && (
        <>
          <SectionHeading>By competency</SectionHeading>
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line-soft">
                  <th
                    scope="col"
                    className="px-5 py-3 text-left text-[0.7rem] font-medium tracking-wider text-faint uppercase"
                  >
                    Competency
                  </th>
                  <th
                    scope="col"
                    className="px-5 py-3 text-left text-[0.7rem] font-medium tracking-wider text-faint uppercase"
                  >
                    Band
                  </th>
                  <th
                    scope="col"
                    className="px-5 py-3 text-left text-[0.7rem] font-medium tracking-wider text-faint uppercase"
                  >
                    What that band means
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-soft">
                {report.competencies.map((rollup) => (
                  <tr key={rollup.competency_id} className="transition-colors hover:bg-glass-2">
                    <td className="px-5 py-3.5 align-top">
                      <code className="font-mono text-xs text-accent-soft">
                        {rollup.competency_id}
                      </code>
                    </td>
                    <td className="px-5 py-3.5 align-top whitespace-nowrap">
                      <span className="font-semibold text-ink">{rollup.band}</span>
                      <span className="text-faint">/5</span>
                    </td>
                    <td className="px-5 py-3.5 align-top text-xs leading-relaxed text-muted">
                      {rollup.band_anchor}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ── the three things to work on ───────────────────────────────── */}
      {report.top_improvements.length > 0 && (
        <>
          <SectionHeading>The three highest-leverage things to work on</SectionHeading>
          <div className="grid gap-4 md:grid-cols-3">
            {report.top_improvements.map((item, index) => (
              <GlowCard key={index} className="h-full p-6" glow="var(--color-glow-cool)">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone="mono">{item.competency_id}</Badge>
                  <span className="font-mono text-xs text-faint">0{index + 1}</span>
                </div>
                <p className="mt-3 text-sm font-semibold text-ink">{item.concept}</p>
                <p className="mt-3 text-xs leading-relaxed text-muted">
                  <span className="text-faint">Why this matters in a real interview: </span>
                  {item.why_it_matters}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-muted">
                  <span className="text-faint">What to add: </span>
                  {item.what_to_add}
                </p>
              </GlowCard>
            ))}
          </div>
        </>
      )}

      {/* ── question by question ──────────────────────────────────────── */}
      <SectionHeading>Question by question</SectionHeading>
      <div className="space-y-4">
        {report.questions.map((question) => (
          <Card key={question.question_id} className="p-6 sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Badge tone="mono">{question.competency_id}</Badge>
              <span className="text-xs text-muted">
                {question.band === null ? (
                  question.status === "skipped" ? (
                    "Skipped"
                  ) : (
                    "Grading…"
                  )
                ) : (
                  <>
                    Band <strong className="font-semibold text-ink">{question.band}</strong>
                    <span className="text-faint">/5</span>
                    {question.hints_used > 0 && ` · ${question.hints_used} hint(s) used`}
                  </>
                )}
              </span>
            </div>

            {question.band !== null && (
              <Meter
                percent={(question.band / 5) * 100}
                valueNow={question.band}
                valueMin={0}
                valueMax={5}
                ariaLabel={`${question.competency_id} band`}
                className="mt-3"
              />
            )}

            <p className="mt-4 text-base leading-relaxed text-ink text-pretty">
              {question.prompt}
            </p>

            {question.transcript && (
              <details className="group mt-4">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md text-xs text-muted transition-colors hover:text-ink">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 20 20"
                    className="h-3.5 w-3.5 transition-transform group-open:rotate-90"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m7.5 5 5 5-5 5" />
                  </svg>
                  What you said
                </summary>
                <blockquote className="mt-3 border-l-2 border-line-strong pl-4 text-sm leading-relaxed text-muted italic">
                  {question.transcript}
                </blockquote>
              </details>
            )}

            {question.unsubstantiated_claim && (
              <Notice className="mt-4 text-[0.8125rem]">
                This topic came from something on your resume, and none of the core concepts came
                through. That&rsquo;s a fact with its evidence attached, not a judgement — it is
                exactly the gap worth closing before a real interview.
              </Notice>
            )}

            <ConceptGroup title="Covered" lines={question.covered} />
            <ConceptGroup title="Partly there" lines={question.partial} />
            <ConceptGroup title="Missed" lines={question.missed} />

            {question.terminology_notes.length > 0 && (
              <p className="mt-5 rounded-lg border border-line-soft bg-glass-2 p-3 text-xs leading-relaxed text-muted">
                <strong className="font-semibold text-ink">
                  Terminology note (zero weight):
                </strong>{" "}
                {question.terminology_notes.join(" ")}
              </p>
            )}
          </Card>
        ))}
      </div>

      <p className="mt-10 text-xs text-faint">
        Session cost: ${report.cost_usd.toFixed(4)}. Shown because a session whose cost is unknown
        is a bug.
      </p>
    </Shell>
  );
}

function ScoreReadout({
  label,
  value,
  format,
}: {
  label: string;
  value: number;
  format: (value: number) => string;
}) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 font-mono text-xl text-ink">{format(value)}</dd>
      <Meter
        percent={value * 100}
        valueNow={Math.round(value * 100)}
        ariaLabel={label}
        className="mt-2"
      />
    </div>
  );
}

function ConceptGroup({ title, lines }: { title: string; lines: ConceptLine[] }) {
  if (lines.length === 0) return null;
  return (
    <section className="mt-6">
      <h3 className="mb-3 text-sm font-semibold text-ink">
        {title} <span className="font-normal text-faint">({lines.length})</span>
      </h3>
      <div className="space-y-3">
        {lines.map((line) => (
          <div
            key={line.concept_id}
            className="relative rounded-xl border border-line-soft bg-glass-2 p-4 pl-5"
          >
            {/* The bar repeats the chip's hue, and the chip repeats the word.
                Neither is load-bearing on its own (NFR-A). A real element and
                not a `before:` pseudo, because the class would have to be
                interpolated and Tailwind cannot see a class it did not read
                in the source. */}
            <span
              aria-hidden="true"
              className={cn(
                "absolute inset-y-3 left-0 w-0.5 rounded-full",
                verdictBar(line.verdict),
              )}
            />
            <div className="flex flex-wrap items-center gap-2">
              <VerdictChip verdict={line.verdict} />
              {line.weight === "core" && <span className="text-xs text-faint">core concept</span>}
              {line.hint_discounted && (
                <span className="text-xs text-partial">credit reduced — a hint pointed here</span>
              )}
            </div>
            <p className="mt-2.5 text-sm text-ink">{line.label}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{line.why_it_matters}</p>
            {line.evidence_quote && (
              <blockquote className="mt-2.5 border-l-2 border-line pl-3 text-xs text-muted italic">
                &ldquo;{line.evidence_quote}&rdquo;
              </blockquote>
            )}
            {line.improvement_note && (
              <p className="mt-2.5 text-xs leading-relaxed text-muted">
                <span className="text-faint">What to add: </span>
                {line.improvement_note}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
