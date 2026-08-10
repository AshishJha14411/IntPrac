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
    <div className="shell wide">
      <h1>Your report</h1>
      <p className="muted">
        {report.mode} mode · {report.seniority} level · {report.graded_questions} of{" "}
        {report.graded_questions + report.pending_questions} questions graded
      </p>

      {report.pending_questions > 0 && (
        <>
          <div className="notice" role="status">
            {report.pending_questions} answer(s) are still being graded. Grading runs after the
            session so it never slows the interview down.
          </div>
          <RefreshWhilePending />
        </>
      )}

      {/* ── overall ───────────────────────────────────────────────────── */}
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Overall</h2>
        <p style={{ fontSize: "1.3rem", margin: "0 0 6px" }}>
          <strong style={{ textTransform: "capitalize" }}>{report.recommendation}</strong>
        </p>
        <p className="small muted">
          Raw {pct(report.overall_raw)} · after accounting for hints{" "}
          {pct(report.overall_hint_adjusted)}. Both are shown because hiding either would be
          dishonest: one hides the help, the other hides the penalty.
        </p>
      </div>

      {/* ── per competency ────────────────────────────────────────────── */}
      {report.competencies.length > 0 && (
        <>
          <h2>By competency</h2>
          <div className="card" style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Competency</th>
                  <th scope="col">Band</th>
                  <th scope="col">What that band means</th>
                </tr>
              </thead>
              <tbody>
                {report.competencies.map((rollup) => (
                  <tr key={rollup.competency_id}>
                    <td>
                      <code>{rollup.competency_id}</code>
                    </td>
                    <td>
                      <strong>{rollup.band}</strong>
                      <span className="muted">/5</span>
                    </td>
                    <td className="small muted">{rollup.band_anchor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ── the three things to work on ───────────────────────────────── */}
      {report.top_improvements.length > 0 && (
        <>
          <h2>The three highest-leverage things to work on</h2>
          {report.top_improvements.map((item, index) => (
            <div className="card" key={index}>
              <p className="small muted" style={{ margin: 0 }}>
                <code>{item.competency_id}</code>
              </p>
              <p style={{ margin: "6px 0" }}>
                <strong>{item.concept}</strong>
              </p>
              <p className="small" style={{ margin: "0 0 6px" }}>
                <span className="muted">Why this matters in a real interview: </span>
                {item.why_it_matters}
              </p>
              <p className="small" style={{ margin: 0 }}>
                <span className="muted">What to add: </span>
                {item.what_to_add}
              </p>
            </div>
          ))}
        </>
      )}

      {/* ── question by question ──────────────────────────────────────── */}
      <h2>Question by question</h2>
      {report.questions.map((question) => (
        <div className="card" key={question.question_id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="small muted mono">{question.competency_id}</span>
            <span className="small muted">
              {question.band === null ? (
                question.status === "skipped" ? (
                  "Skipped"
                ) : (
                  "Grading…"
                )
              ) : (
                <>
                  Band <strong>{question.band}</strong>/5
                  {question.hints_used > 0 && ` · ${question.hints_used} hint(s) used`}
                </>
              )}
            </span>
          </div>

          <p style={{ fontSize: "1.05rem", marginTop: 10 }}>{question.prompt}</p>

          {question.transcript && (
            <details>
              <summary className="small muted" style={{ cursor: "pointer" }}>
                What you said
              </summary>
              <blockquote>{question.transcript}</blockquote>
            </details>
          )}

          {question.unsubstantiated_claim && (
            <div className="notice small" style={{ margin: "12px 0" }}>
              This topic came from something on your resume, and none of the core concepts came
              through. That&rsquo;s a fact with its evidence attached, not a judgement — it is
              exactly the gap worth closing before a real interview.
            </div>
          )}

          <ConceptGroup title="Covered" lines={question.covered} />
          <ConceptGroup title="Partly there" lines={question.partial} />
          <ConceptGroup title="Missed" lines={question.missed} />

          {question.terminology_notes.length > 0 && (
            <p className="small muted" style={{ marginTop: 12 }}>
              <strong>Terminology note (zero weight):</strong>{" "}
              {question.terminology_notes.join(" ")}
            </p>
          )}
        </div>
      ))}

      <p className="small muted" style={{ marginTop: 32 }}>
        Session cost: ${report.cost_usd.toFixed(4)}. Shown because a session whose cost is
        unknown is a bug.
      </p>
    </div>
  );
}

function ConceptGroup({ title, lines }: { title: string; lines: ConceptLine[] }) {
  if (lines.length === 0) return null;
  return (
    <section style={{ marginTop: 16 }}>
      <h3 style={{ margin: "0 0 4px" }}>
        {title} <span className="muted small">({lines.length})</span>
      </h3>
      {lines.map((line) => (
        <div className={`concept ${line.verdict}`} key={line.concept_id}>
          <div className="row" style={{ gap: 8 }}>
            <VerdictChip verdict={line.verdict} />
            {line.weight === "core" && (
              <span className="small muted">core concept</span>
            )}
            {line.hint_discounted && (
              <span className="small muted">credit reduced — a hint pointed here</span>
            )}
          </div>
          <p style={{ margin: "8px 0 4px" }}>{line.label}</p>
          <p className="small muted" style={{ margin: "0 0 6px" }}>
            {line.why_it_matters}
          </p>
          {line.evidence_quote && (
            <blockquote className="small">&ldquo;{line.evidence_quote}&rdquo;</blockquote>
          )}
          {line.improvement_note && (
            <p className="small" style={{ margin: "6px 0 0" }}>
              <span className="muted">What to add: </span>
              {line.improvement_note}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}

/** Never colour alone (NFR-A): each chip carries a glyph and a word too. */
function VerdictChip({ verdict }: { verdict: ConceptLine["verdict"] }) {
  const glyph = {
    covered: "✓",
    partial: "◐",
    missing: "○",
    contradicted: "✕",
  }[verdict];
  return (
    <span className={`chip ${verdict}`}>
      <span aria-hidden="true">{glyph}</span>
      {verdict}
    </span>
  );
}
