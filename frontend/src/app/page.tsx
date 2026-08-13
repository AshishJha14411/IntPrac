import { ArrowRight, FileText, Lightbulb, ListChecks, Target } from "lucide-react";
import Link from "next/link";
import { Aurora, GridGround, Spotlight } from "@/components/ui/backgrounds";
import { BentoCard, BentoGrid } from "@/components/ui/bento";
import { GradientBorderLink } from "@/components/ui/button";
import { GlowCard } from "@/components/ui/card";
import { Notice } from "@/components/ui/feedback";
import { Band } from "@/components/ui/shell";
import { TextGenerate } from "@/components/ui/text-generate";

/** Static landing page -- the thesis in sixty seconds (P3 exit criterion). */
export default function Home() {
  return (
    <>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section className="relative isolate overflow-hidden">
        <Spotlight className="-top-40 left-0 md:-top-20 md:left-60" />
        <Aurora />
        <GridGround />

        <div className="relative mx-auto max-w-4xl px-5 pt-20 pb-16 text-center sm:px-6 sm:pt-28">
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-glass-2 px-3.5 py-1.5 text-xs text-muted backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-covered shadow-[0_0_10px_2px_rgba(52,211,153,0.7)]" />
            Terminology carries zero weight
          </span>

          <h1 className="text-gradient text-4xl font-semibold tracking-tight text-balance sm:text-6xl sm:leading-[1.05]">
            Practise the interview.
            <br />
            Find out what you actually missed.
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted text-pretty sm:text-lg">
            <TextGenerate text="You are scored on understanding, not vocabulary. Explain the right mechanism in plain words and you get full credit — even with no technical terminology at all. Use the correct term with the wrong mental model and you don't." />
          </p>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <GradientBorderLink href="/practice">
              Start a practice session
              <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </GradientBorderLink>
            <Link
              href="/login"
              className="rounded-lg px-2 py-1 text-sm text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              Already have an account?
            </Link>
          </div>
        </div>
      </section>

      {/* ── the claim, made concrete ─────────────────────────────────────── */}
      <Band className="mx-auto max-w-5xl px-5 py-16 sm:px-6">
        <GlowCard className="p-7 sm:p-9">
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:items-center">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-ink text-balance">
                What that means in practice
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                For a question about why deep pagination gets slow, all of these earn full credit
                for the core idea:
              </p>
              <p className="mt-5 text-sm text-faint">
                Nobody ever has to say the word{" "}
                <span className="font-mono text-accent-soft">&ldquo;keyset&rdquo;</span>.
              </p>
            </div>

            <ul className="space-y-3">
              {[
                "it has to walk past all those rows first",
                "it counts through everything it’s skipping",
                "like a bookmark instead of counting pages",
              ].map((quote) => (
                <li
                  key={quote}
                  className="flex items-start gap-3 rounded-xl border border-line-soft bg-glass-2 px-4 py-3"
                >
                  <span
                    aria-hidden="true"
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-covered/40 bg-covered/12 text-[0.7rem] font-bold text-covered"
                  >
                    ✓
                  </span>
                  <span className="text-sm leading-relaxed text-ink/90">
                    &ldquo;{quote}&rdquo;
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </GlowCard>
      </Band>

      {/* ── how a session works ──────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-5 pb-16 sm:px-6">
        <h2 className="mb-2 text-2xl font-semibold tracking-tight text-ink">
          How a session works
        </h2>
        <p className="mb-8 max-w-2xl text-sm leading-relaxed text-muted">
          Four steps, and you can read every one of them before you commit to anything.
        </p>

        <BentoGrid className="lg:grid-cols-2">
          <BentoCard
            step="Step 1"
            icon={<FileText aria-hidden="true" className="h-4 w-4" />}
            title="Paste a job description, or upload a resume"
          >
            It is used to choose <strong className="font-medium text-ink">which topics you are
            asked about</strong> — and nothing else. It never reaches the thing that scores you.
          </BentoCard>

          <BentoCard
            step="Step 2"
            icon={<ListChecks aria-hidden="true" className="h-4 w-4" />}
            title="Read the plan before you start"
          >
            Which competencies, at which level, and how many questions. No surprises, and nothing
            inferred from your documents that you cannot see.
          </BentoCard>

          <BentoCard
            step="Step 3"
            icon={<Lightbulb aria-hidden="true" className="h-4 w-4" />}
            title="Answer in your own words"
          >
            Speak it or type it — scored identically. Stuck? Three graduated hints point at the{" "}
            <em className="text-ink/90 not-italic">concept</em>, never the term.
          </BentoCard>

          <BentoCard
            step="Step 4"
            icon={<Target aria-hidden="true" className="h-4 w-4" />}
            title="See exactly what you missed"
          >
            What you covered, what you missed, and one sentence per gap explaining the idea you
            didn&rsquo;t reach.
          </BentoCard>
        </BentoGrid>
      </section>

      {/* ── the guarantee ────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-5 pb-24 sm:px-6">
        <Notice tone="accent" className="p-6">
          <strong className="font-semibold text-ink">What is never scored:</strong> accent,
          fluency, grammar, speaking speed, confidence, or anything inferred from your face or
          voice. Your resume decides what you are asked; only your answers decide your rating.
        </Notice>
      </section>
    </>
  );
}
