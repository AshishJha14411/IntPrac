import Link from "next/link";

/** Static landing page -- the thesis in sixty seconds (P3 exit criterion). */
export default function Home() {
  return (
    <div className="shell">
      <h1>Practise the interview. Find out what you actually missed.</h1>
      <p className="muted" style={{ fontSize: "1.05rem" }}>
        You are scored on <strong>understanding, not vocabulary</strong>. Explain the right
        mechanism in plain words and you get full credit — even with no technical terminology at
        all. Use the correct term with the wrong mental model and you don&rsquo;t.
      </p>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>What that means in practice</h2>
        <p className="small muted">
          For a question about why deep pagination gets slow, all of these earn full credit for
          the core idea:
        </p>
        <ul className="small">
          <li>&ldquo;it has to walk past all those rows first&rdquo;</li>
          <li>&ldquo;it counts through everything it&rsquo;s skipping&rdquo;</li>
          <li>&ldquo;like a bookmark instead of counting pages&rdquo;</li>
        </ul>
        <p className="small muted" style={{ marginBottom: 0 }}>
          Nobody ever has to say the word &ldquo;keyset&rdquo;.
        </p>
      </div>

      <h2>How a session works</h2>
      <ol className="stack">
        <li>
          Paste a job description (or upload a resume). It is used to choose{" "}
          <strong>which topics you are asked about</strong> — and nothing else.
        </li>
        <li>
          You get a plan you can read before you start: which competencies, at which level.
        </li>
        <li>
          Answer in your own words. Stuck? Three graduated hints point at the{" "}
          <em>concept</em>, never the term.
        </li>
        <li>
          Afterwards: what you covered, what you missed, and one sentence per gap explaining the
          idea you didn&rsquo;t reach.
        </li>
      </ol>

      <div className="row" style={{ marginTop: 24 }}>
        <Link href="/practice">
          <button>Start a practice session</button>
        </Link>
        <Link href="/login" className="small muted">
          Already have an account?
        </Link>
      </div>

      <div className="notice small" style={{ marginTop: 32 }}>
        <strong>What is never scored:</strong> accent, fluency, grammar, speaking speed,
        confidence, or anything inferred from your face or voice. Your resume decides what you
        are asked; only your answers decide your rating.
      </div>
    </div>
  );
}
