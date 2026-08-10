# AI Interview Platform — Requirements Specification

**Status:** Draft v0.1 · **Owner:** Ashish Kr Jha · **Date:** 2026-07-27

---

## 1. Purpose & Product Thesis

A voice-driven interview platform that (a) lets **candidates practise realistic
interviews and learn what their answers missed**, and (b) lets **HR/hiring teams
review a recorded, AI-assessed interview and make a faster, better-informed
decision**.

The differentiator is the **assessment philosophy**:

> We score **understanding, not vocabulary.** A candidate who explains the right
> mechanism in plain words scores higher than one who recites the correct term
> with the wrong mental model. When a candidate is stuck, the interviewer helps
> them toward the **concept**, never the terminology.

Everything in this spec — the rubric model, the hint policy, the feedback
report, the HR review screen — exists to serve that thesis.

### 1.1 Two products, one engine

| | Practice Mode | Official Mode |
|---|---|---|
| Who starts it | Candidate, self-serve | HR sends an invite for a job posting |
| Who sees results | Candidate only | HR/hiring team; candidate sees a limited view |
| Feedback | Immediate, full gaps + model answers | Gated on HR decision (org-configurable) |
| Purpose | Improvement | Screening |

Same interview engine, same rubric, different visibility rules. This
distinction resolves the tension between "teach the candidate" and "assess the
candidate" and must be modelled explicitly from day one.

### 1.2 The scoring isolation boundary (core architectural constraint)

> **The resume and JD decide WHAT IS ASKED. Only the interview decides THE
> RATING.**

> ⚠ **Amended once plan synthesis shipped. Read this first.**
>
> The bank could only ask about topics somebody had authored, and only
> backend-engineering, databases and part of system-design ever were — 32 of 129
> competencies. So reduction could not name anything else, and a frontend
> candidate, a Salesforce administrator or a clinical trial manager was
> interviewed about Postgres indexing. Outside software nobody on this project
> can author that content, or judge it if they did.
>
> `services/plan_synthesis` therefore writes the interview from the documents in
> one model call. Two clauses below changed as a result, and the honest version
> is here rather than in a commit message:
>
> * **IR-2 is relaxed, deliberately and narrowly.** A rubric may now be written
>   from the candidate's documents. It must still clear `validate_question` —
>   the same bar the hand-authored banks clear — and is rejected, not
>   downgraded, if it does not.
> * **IR-3 no longer holds across candidates.** Two people are no longer asked
>   the same questions, so scores are a personal development signal and not a
>   ranking. Invariance survives only in the narrow form the tests assert: the
>   same rubric and the same answer produce the same verdict.
>
> **IR-1 is untouched and is now the load-bearing one.** The grader still
> receives the rubric, the neutral wording and the transcript, and nothing else
> — `build_grading_payload` has no parameter that could carry prose, and
> `tests/unit/test_score_invariance.py` asserts it. A document decides what you
> are asked about. It never talks to the thing that scores you.

Resume and JD free text are used for exactly one purpose: to select the
**domain, topics and seniority** of the interview. At that point they are
reduced to a small, validated, closed-vocabulary set of selectors:

```
resume text ─┐
             ├─►  [ REDUCTION ]  ─►  { competency_ids[], seniority, domain }  ─►  everything downstream
JD text ─────┘   (schema-validated,          ▲
                  closed taxonomy)           │
                                    ═════════╪═════════  TRUST BOUNDARY
                  free text is DISCARDED here; nothing past this
                  line ever receives resume or JD prose
```

Downstream of the boundary — question authoring, the rubric, the grader, the
score — only the selectors exist. Consequences, all of them requirements:

- **IR-1** The grader receives the **rubric + answer transcript only**. Never
  resume text, never JD text, never the candidate's name or history.
- **IR-2** The **rubric is never authored from resume/JD prose.** It comes from
  the question bank / taxonomy keyed by `(competency_id, seniority)`. This is
  the part that "the grader can't see the resume" alone does **not** protect: the
  rubric *is* the standard, so if prose could shape the rubric, an injected
  resume could lower the bar while scoring stayed nominally isolated.
- **IR-3** **Score invariance:** two candidates giving semantically identical
  answers to the same question **must** receive identical scores, regardless of
  their resumes. This is a testable property (§6.7) and a fairness guarantee, not
  an aspiration.
- **IR-4** The reduction step's output is schema-validated against a **closed
  competency taxonomy**. Anything not in the taxonomy is discarded, so the blast
  radius of a hostile document is "wrong topics chosen", never "scoring
  compromised".
- **IR-5** Resume-derived *question framing* is permitted but cosmetic — see
  §5.0.

**Why this matters beyond security:** it makes every score explainable in terms
of what the candidate actually said, and it makes ratings comparable across
candidates. It also collapses two open design questions (see §12) — with topics
constrained to a taxonomy, a curated question bank becomes the natural fit, and
comparability (FR-P4) falls out for free.

### 1.3 Primary context & scale assumptions

**Real primary users: the author and a small group of friends — computer
engineering / software development candidates preparing for real interviews.**
Secondary purpose: a **portfolio showcase** demonstrating architecture and
judgement. It is *not* a commercial multi-tenant hiring product in v1.

This has concrete design consequences:

| Assumption | Consequence |
|---|---|
| Tens of users, not thousands | No sharding, no read replicas, no queue autoscaling. Single Postgres + one worker is correct. |
| ~~Domain is **CS / software engineering**~~ **Superseded.** | The authored taxonomy is still deep on CS/dev (Appendix C), but it is no longer the limit. Plan synthesis writes questions for whatever profession the documents describe, and caches them, so breadth costs authoring time rather than being refused. The original reasoning — that a curated bank turns per-interview spend into one-time authoring spend — still holds and is *why* this works: a synthesised rubric is written once at roughly $0.003 and reused forever, so a whole new profession costs about ten cents. |
| Practice is the main flow | Candidate feedback quality is the #1 product priority; HR review is built for **showcase + occasional peer review**, not pipeline throughput. |
| Costs come out of a personal wallet | **Cost per interview is a hard design constraint, not a metric** (§8.3). |
| Peers practising, not adversaries | Anti-cheating/integrity signalling (§9.5) drops to "nice-to-have, last". Nobody is gaming a practice interview against themselves. |

**Cost, and why the bank design saves it.** Because questions come from a
**finite curated bank** (IR-2), their spoken audio is synthesised **once, ever**
and reused for every candidate forever — TTS cost trends to zero as the bank
stabilises. That leaves only two real variable costs: STT on candidate speech
(per minute spoken) and LLM grading (per answer). Reduction runs once per
resume/JD, not per interview. A curated bank turns the economics from
"per-interview LLM spend" into "one-time authoring spend" — which is exactly
what makes regular practice affordable for a hobby project.

**Peer review, not HR.** In this context the "HR reviewer" role is really *a
friend reviewing your interview*. The workspace (§4.10) is unchanged in shape,
but the framing in the UI should be "reviewer", and the review queue is a handful
of sessions, not a funnel.

---

## 2. Scope

### 2.1 In scope (v1)
- Email/password + OAuth login; org-scoped roles.
- Resume upload (PDF/DOCX) → parsed into a structured, versioned profile.
- Job description (JD) input by paste or upload → parsed into requirements.
- Three interview generation modes: **Resume-only**, **JD-only**, **Resume × JD**.
- Voice interview: questions **spoken** to the candidate (TTS), answers captured
  by **streaming speech-to-text**, with a typed fallback.
- Webcam video recording of the session for human review.
- Concept-based evaluation: per answer, what was **covered / partial / missed**,
  and **what could have been added**.
- Candidate improvement report.
- HR review workspace: video + synced transcript, per-question gaps, AI rating,
  human rating, and an advance/hold/reject decision.

### 2.2 Explicitly OUT of scope (v1) — and why
| Excluded | Reason |
|---|---|
| **Emotion / affect / "confidence" scoring from video or voice tone** | Scientifically weak, demonstrably biased, and restricted or banned in several jurisdictions. Video exists for *human* review only. |
| Any **automated rejection** | A human must make every adverse decision (see §9.3). AI output is advisory. |
| Accent, fluency, or grammar scoring | Directly conflicts with §1's thesis and creates national-origin bias. |
| Live coding / IDE / whiteboard | Separate product surface; may follow in P3. |
| Multi-interviewer live panels | v1 is async: AI conducts, humans review later. |
| ATS write-back integrations | Not applicable at this scale (§1.3). |
| ~~Non-CS/engineering domains (sales, finance, …)~~ **Now in scope.** | Plan synthesis writes and caches questions for any profession the documents describe (§1.2). Verified against a clinical trial management JD and a marketing JD. What remains out of scope is *authoring* those domains by hand — nobody here could judge the result. |
| Statistical adverse-impact / bias auditing | Needs population volume to be meaningful; a handful of friends can't produce a valid signal. The *fairness mechanisms* (IR-3, name-blind grading) still apply — the statistical reporting doesn't. |
| Horizontal scale work (replicas, sharding, autoscaling) | Wrong problem at tens of users; would be architecture theatre. |

### 2.3 Ambiguity resolved
The brief said "2 methods" then described three. **Spec'd as three modes**
(§5). Resume × JD is the flagship for hiring; Resume-only and JD-only are the
main practice entry points.

---

## 3. Personas & Roles

| Role | Description | Core needs |
|---|---|---|
| **Candidate** | Practising, or invited to an official interview | Low-friction start, fair questions, help when stuck, actionable gaps |
| **Recruiter / HR Reviewer** | Screens candidates for a posting | Fast triage, evidence not vibes, jump to the moment in the video |
| **Hiring Manager** | Makes the call | Depth on shortlisted candidates, per-competency signal |
| **Org Admin** | Owns the workspace | Members, postings, retention & feedback policy |
| **Platform Admin** | Operates the service | Support, audits, rubric versioning |

**Multi-tenancy is a hard requirement.** Every domain row is scoped to an
`organization_id`, and every query is filtered by the caller's org membership.
Candidates are global identities that can be linked to many orgs.

---

## 4. Functional Requirements

### 4.1 Accounts & Access — `FR-A`
- **FR-A1** Users register/log in with email+password or OAuth (Google).
- **FR-A2** Email verification required before an *official* interview.
- **FR-A3** Sessions use short-lived access tokens + rotating refresh tokens;
  refresh reuse is detected and revokes the family.
- **FR-A4** Role assignment is per-org (`org_members.role`), never global.
- **FR-A5** Permissions are checked through a central policy layer against a
  capability enum — never by comparing role name strings at call sites.
- **FR-A6** HR invites a candidate to a posting by email; invite is a
  single-use, expiring token that provisions or links the candidate account.

### 4.2 Resume Intake — `FR-R`
- **FR-R1** Candidate uploads a resume: PDF or DOCX, ≤ 10 MB.
- **FR-R2** Upload goes **directly to object storage via a short-lived
  presigned URL**; the API only signs the request and records metadata. Files
  never stream through the application server.
- **FR-R3** Parsing is an **asynchronous job**. The UI shows
  `uploaded → parsing → ready | failed` and never blocks on it.
- **FR-R4** Parsing produces a structured `ResumeProfile`:
  identity (name/contact), skills, roles (title, org, dates, seniority),
  projects (what, stack, candidate's stated contribution), education,
  certifications.
- **FR-R5** Every extracted item carries **provenance** — the source text span
  it came from — so a question can cite the exact bullet it is probing and HR
  can see the extraction wasn't invented.
- **FR-R6** Re-upload creates a **new version**. Completed interviews keep
  pointing at the version they used; results are never retroactively changed.
- **FR-R7** The candidate can review and **correct** parsed fields before an
  interview. Corrections are stored as an overlay with an edit audit trail.
- **FR-R8** Resume text is treated as **untrusted input** (see §9.4).
- **FR-R9** Candidate can delete a resume and all derived data (§9.2).

### 4.3 Job Description Intake — `FR-J`
- **FR-J1** HR (or a candidate, in practice mode) supplies a JD by paste, file,
  or URL fetch.
- **FR-J2** Parsing produces a `JDProfile`: role title, seniority, required
  competencies, preferred competencies, domain, and responsibilities — each
  with provenance and a `required | preferred` weight.
- **FR-J3** JDs are reusable across candidates and versioned like resumes.
- **FR-J4** Ambiguous/thin JDs (< N extractable requirements) raise a warning
  and prompt for enrichment rather than silently producing a weak interview.

### 4.4 Interview Planning — `FR-P`
- **FR-P1** Before any question is asked, the system generates a persisted
  **Interview Plan**: an ordered blueprint of question *slots*, each with a
  target competency, difficulty tier, and source basis.
- **FR-P2** Plan parameters: mode, target duration (10/20/30/45 min), question
  count, difficulty ceiling, competency mix.
- **FR-P3** The plan is deterministic and reviewable *before* the session
  starts. HR can preview and edit the plan for a posting; a plan can be saved
  as a reusable **template** so every candidate for a posting gets a comparable
  interview.
- **FR-P4** **Comparability requirement:** two candidates interviewed against
  the same posting must receive the same competency coverage and difficulty
  distribution, even though wording differs. Adaptivity happens *within* a
  question (follow-ups), not by silently changing which competencies are tested.
- **FR-P5** Each generated question is stored with its **rubric** at generation
  time (§6.1) — not graded ad hoc later.

### 4.5 Interview Modes — see §5.

### 4.6 The Live Interview Session — `FR-S`
- **FR-S1** Session state machine:
  `created → planned → consent_pending → device_check → in_progress → completed | abandoned → graded → published → reviewed`
  Transitions are explicit and audited; illegal transitions are rejected.
- **FR-S2** **Consent gate.** Before any capture begins the candidate is shown,
  and must actively accept: that AI conducts and assesses the interview; that
  audio/video/transcript are recorded; what is scored and what is not; who can
  view it; retention period; and how to withdraw. Consent is timestamped and
  versioned. No consent → no recording, no session.
- **FR-S3** **Device check** before start: camera preview, mic level meter, a
  test utterance echoed back as text so the candidate trusts the transcription,
  and a network check. Failures are actionable, not fatal.
- **FR-S4** Per-question turn loop:
  1. Question is **spoken** (TTS) and simultaneously shown as text.
  2. Streaming STT captures the answer; **interim transcript is displayed live**
     so the candidate can see they're being heard correctly.
  3. Turn ends on: candidate presses "Done", or `SILENCE_END` (default 3 s of
     silence after speech), or the per-question cap is reached.
  4. Optional **follow-up** (≤ 2 per question) to probe a shallow or ambiguous
     answer.
  5. Optional **hint** if requested or triggered (§6.3).
  6. Answer + transcript + timings are persisted before advancing.
- **FR-S5** **Barge-in:** the candidate may start speaking over the question;
  TTS ducks and stops.
- **FR-S6** Candidate may **re-hear** a question (cached audio, no cost, logged)
  and may **skip** a question (recorded as skipped, not as wrong).
- **FR-S7** **Typed-answer fallback** is always available — required for
  accessibility, and the automatic fallback when STT confidence is persistently
  low or the mic fails.
- **FR-S8** **Resumability:** a dropped connection or refresh must resume at the
  current question with prior answers intact. Answer submission is
  **idempotent** (client-supplied key) so a retried submit never double-records.
- **FR-S9** A visible progress indicator and remaining-time budget.
- **FR-S10** Pause is allowed in practice mode; in official mode, pauses are
  time-boxed and recorded.
- **FR-S11** Accommodation flag (e.g. extended time, no time pressure) settable
  by the candidate pre-session and, in official mode, invisible to scoring but
  disclosed to HR only as "accommodation applied" without medical detail.

### 4.7 Voice Pipeline — `FR-V`
- **FR-V1** Questions are synthesised to audio and **cached** keyed by
  (question text, voice, version) — re-asks and repeat candidates are instant
  and free.
- **FR-V2** STT is **streaming**, producing interim + final transcripts with
  per-segment timestamps and confidence.
- **FR-V3** Final transcript stores word/segment **timings aligned to the video
  timeline**, which is what powers HR's "jump to this answer" (FR-H4).
- **FR-V4** Low-confidence spans are marked in the stored transcript and shown
  as uncertain to HR — never silently guessed at.
- **FR-V5** The transcript is the **artifact of record** for grading. Grading
  never consumes raw audio in v1, which keeps assessment auditable and
  reproducible.
- **FR-V6** Language: English (v1), with the pipeline parameterised by locale.

### 4.8 Video & Media — `FR-M`
- **FR-M1** Webcam video (+ audio) is recorded for the session.
- **FR-M2** Media is uploaded in **chunks to object storage via presigned
  URLs**, progressively during the session, so a completed session is not
  followed by a large fragile upload.
- **FR-M3** If video upload fails, the interview and its assessment still
  stand; media is marked `unavailable`. Video is evidence, not a dependency.
- **FR-M4** Playback is HR-only, via short-lived signed URLs; media is never
  public and never hot-linkable.
- **FR-M5** Video is **not** analysed by AI in v1 (§2.2).

### 4.9 Evaluation & Feedback — see §6.

### 4.10 HR Review Workspace — `FR-H`
- **FR-H1** A **review queue** per posting: candidate, completion time, AI
  overall rating, per-competency mini-bars, integrity flags, review status.
  Sortable and filterable; supports keyset pagination for large volumes.
- **FR-H2** Candidate detail view shows, per question: the question, the
  competency it targeted, the answer transcript, and the **concept coverage
  chips** (covered / partial / missed) with the "what could have been added"
  note.
- **FR-H3** An overall panel: AI rating per competency with the **evidence
  behind each score**, strengths, gaps, and a recommendation band — never a
  bare number.
- **FR-H4** **Transcript ↔ video sync:** clicking any question or transcript
  segment seeks the video to that moment. This is the feature that makes review
  fast enough to actually happen.
- **FR-H5** Reviewer records their **own rating** per competency + overall, free
  notes, and a decision: `advance | hold | reject`.
- **FR-H6** AI and human ratings are both persisted, enabling an
  **agreement/calibration metric** over time (§8.4). Divergence is a product
  signal, not an embarrassment.
- **FR-H7** Decisions require a reason code; the AI rating alone can never
  finalise a rejection (§9.3).
- **FR-H8** Side-by-side comparison of shortlisted candidates on the same
  posting, competency by competency.
- **FR-H9** Full **audit trail**: who viewed, who rated, what changed, when.

### 4.11 Candidate Feedback Report — `FR-F`
- **FR-F1** Practice mode: report available immediately on completion.
- **FR-F2** Report contents, per question: what you said (transcript), the
  concepts you **covered**, the concepts you **missed or half-touched**, and a
  **concise model answer sketch** for each gap — written to teach the idea, not
  to supply the buzzword.
- **FR-F3** Overall: competency profile, the 3 highest-leverage things to
  improve, and *why each matters in a real interview*.
- **FR-F4** Cross-session **progress tracking**: competency scores over time, so
  practice has a visible arc.
- **FR-F5** Hints used are shown honestly, with both raw and hint-adjusted
  scores.
- **FR-F6** Official mode: candidate visibility is org-configurable
  (`none | after_decision | always`), defaulting to `after_decision`.
- **FR-F7** Report is exportable (PDF) for the candidate's own use.

---

## 5. Interview Modes

### 5.0 What the modes actually differ in

All three modes are **the same pipeline with a different reduction input**. A
mode changes only *how the topic selectors are chosen* — never how answers are
scored (§1.2).

| Mode | Reduction input | Selector output |
|---|---|---|
| A `resume` | resume only | topics the candidate claims |
| B `jd` | JD only | topics the role requires |
| C `combined` | both | topics the role requires, prioritised by the Fit Map |

**Question framing vs. question standard — `FR-M0`**
- **FR-M0a** A question has two parts: **framing** (the human-sounding wrapper)
  and **standard** (the rubric). Only framing may reference resume specifics
  ("you mentioned working with a message queue — how would you handle a consumer
  falling behind?").
- **FR-M0b** The standard is always bank-authored for
  `(competency_id, seniority)` and is **identical** for every candidate asked
  about that competency at that level — regardless of framing.
- **FR-M0c** Framing text is sanitised and length-capped, and is **never** passed
  to the grader. Worst case for a hostile resume is an oddly-worded question — a
  quality defect, never a scoring defect.
- **FR-M0d** Framing is optional. If sanitisation rejects it, the question falls
  back to its neutral bank wording and the interview proceeds.

### 5.1 Mode A — Resume-only (`resume`)
**Intent:** probe the depth behind what the candidate claims.

- **FR-M-A1** Resume items select the **topics**, and may supply question
  **framing** (FR-M0), each citing its provenance span. The rubric behind the
  question is still bank-authored (IR-2).
- **FR-M-A2** Question archetypes: *depth* ("you built X — walk me through why
  you chose that approach"), *decision* ("what would you do differently"),
  *contribution* ("what was yours specifically vs the team's"), *edge*
  ("what broke, and how did you find out").
- **FR-M-A3** Distribution is weighted toward recent and prominently-claimed
  experience.
- **FR-M-A4** `unsubstantiated_claim` is a **derived** flag, not a grader
  judgement: the system already knows "this question's topic came from resume
  item Y" (link metadata, no prose), so if the answer scored `missing` on every
  `core` concept, the flag follows by rule. This keeps the resume-verification
  capability **without** letting resume text influence the score — the grader
  still never sees the claim, it just scores the answer, and the join happens
  afterwards. Shown to HR as a fact with the evidence, not a moral judgement.

### 5.2 Mode B — JD-only (`jd`)
**Intent:** can this person do *this job*, independent of their history?

- **FR-M-B1** Questions derive from JD competencies, weighted `required` over
  `preferred`.
- **FR-M-B2** Questions are background-neutral — no assumption of prior
  exposure; scenario-framed ("suppose you needed to …").
- **FR-M-B3** Primary practice mode for candidates targeting a role they don't
  yet match. Explicitly supports "I'm interviewing for this next month."

### 5.3 Mode C — Resume × JD (`combined`) — flagship
**Intent:** fit assessment, gap-aware.

- **FR-M-C1** The system first computes a **Fit Map**: for each JD competency,
  classify the resume evidence as `strong | partial | absent`.
- **FR-M-C2** The Fit Map drives question allocation:
  - `strong` → **verify** (is the claimed depth real?)
  - `partial` → **probe the boundary** (where does their knowledge stop?)
  - `absent` → **assess learnability** (reasoning from first principles, and
    honest self-assessment — *not* punished as ignorance)
- **FR-M-C3** The Fit Map is shown to HR alongside results — it explains why
  each question was asked.
- **FR-M-C4** Handles the "absent" case with care: the goal is to find out
  whether someone can *get there*, not to trap them.

---

## 6. The Assessment Model (core of the product)

### 6.1 Concept rubrics, bound to the question — `FR-E1`
Each question is persisted with the **expected-concept set** it will be graded
against, resolved from the bank at plan time (never invented at grading time).
Each concept has:

| Field | Meaning |
|---|---|
| `concept_id` | Stable id within the rubric |
| `label` | The idea, in plain language ("in-flight requests must drain before shutdown") |
| `weight` | `core` \| `supporting` \| `bonus` |
| `why_it_matters` | One line, used verbatim in candidate feedback |
| `acceptable_signals` | Examples of *paraphrases/analogies* that count as understanding |
| `common_misconceptions` | What a wrong mental model looks like |

**Rubric provenance — `FR-E1a`.** A rubric is keyed by
`(competency_id, seniority)` and authored from the **question bank / taxonomy**.
It is **never** derived from resume or JD prose (IR-2). The same competency at
the same level yields the same rubric for every candidate — which is
simultaneously the fairness guarantee (IR-3), the comparability guarantee
(FR-P4), and the injection defence (§9.4).

Rubrics are **versioned**. Re-grading with a newer rubric version is possible
and always recorded as a distinct evaluation — never an in-place overwrite.

### 6.2 Grading = concept coverage, not text similarity — `FR-E2`
For each expected concept the grader emits exactly one verdict:

`covered` · `partial` · `missing` · `contradicted`

…each with a **supporting quote from the candidate's own words** (or an explicit
"no supporting statement"). Grading rules that are non-negotiable:

- **FR-E2a** A correct mechanism described in the candidate's own words, or by
  analogy, is `covered` — **even with no technical terminology at all**.
- **FR-E2b** Correct terminology with an incorrect underlying mechanism is
  `contradicted`, **not** `covered`. Jargon is never evidence by itself.
- **FR-E2c** Wrong *names* with right *ideas* are not penalised. Terminology
  accuracy may be reported as an informational note; it carries **zero weight**
  in the score.
- **FR-E2d** Filler, disfluency, grammar, accent, and speaking speed are never
  assessed.
- **FR-E2e** The grader must cite evidence for every verdict. A verdict without
  a quote or an explicit absence marker is invalid and triggers a re-grade.

### 6.3 Scored axes — `FR-E3`
| Axis | Weight | What it measures |
|---|---|---|
| **Conceptual correctness** | highest | Is the mental model right? |
| **Depth** | high | Beyond the headline: mechanisms, trade-offs, failure modes |
| **Concrete grounding** | medium | Real examples, specifics, lived detail |
| **Structure** | low | Was the explanation followable? (Structure ≠ eloquence) |
| ~~Terminology~~ | **0** | Reported only, never scored |

Scores are **1–5 per competency with written anchors** for each level (so the
scale means the same thing across candidates and over time), rolled up to a
weighted overall plus a **recommendation band** — never a naked percentage.

### 6.4 The hint policy — "help with concepts, not terms" — `FR-E4`
- **FR-E4a** Three graduated hint levels, and never past L3:
  - **L1 — Reframe.** Same question, different words. Zero content added.
  - **L2 — Conceptual signpost.** Point at the *area to think about*
    ("think about what happens to requests already in flight") — names no term,
    supplies no answer.
  - **L3 — Partial concept reveal.** State one `core` concept plainly and ask
    the candidate to build on it.
- **FR-E4b** A hint must **never** supply the terminology or a term the rubric
  is looking for. Hints target the mental model.
- **FR-E4c** Triggers: explicit candidate request; sustained silence after the
  question; or a detected off-track answer (bounded to 1 auto-hint/question).
- **FR-E4d** Every hint is recorded with level, trigger, timestamp, and text.
- **FR-E4e** Two scores are always kept: **raw** and **hint-adjusted**. Both are
  shown to HR and to the candidate. Hints reduce credit on the concepts they
  touched — never the whole answer.
- **FR-E4f** The candidate is told a hint is being offered. No silent scoring
  penalties.

### 6.5 Follow-ups — `FR-E5`
- **FR-E5a** Triggered when an answer is on-topic but shallow, ambiguous, or
  leaves a `core` concept untouched.
- **FR-E5b** Max 2 per question, and they must stay inside the question's
  existing rubric — a follow-up may not introduce a new competency (FR-P4).
- **FR-E5c** Follow-ups are neutral in tone and never leading ("tell me more
  about how that behaves under load", not "isn't it because of X?").

### 6.6 Grader reliability — `FR-E6`
- **FR-E6a** Grading output is schema-validated; malformed output is retried,
  then quarantined for human review rather than silently defaulted.
- **FR-E6b** Deterministic settings (low temperature, pinned model version).
  The model version and rubric version are stored on every evaluation, so any
  score is reproducible and explainable months later.
- **FR-E6c** A **golden set** of pre-scored answers runs on every prompt/model
  change; drift beyond a threshold blocks the change.
- **FR-E6d** Same-answer re-grade variance is monitored as a quality metric.
- **FR-E6e** Grading is asynchronous, queued, retried with backoff, and
  idempotent per (answer, rubric version, model version).

### 6.7 Score-invariance test (enforces IR-3) — `FR-E7`
- **FR-E7a** A standing test grades the **same answer transcript** against the
  same rubric while varying the attached resume (including a deliberately
  flattering one and an injection-laden one). All runs **must** produce identical
  concept verdicts. Any divergence is a release blocker: it means resume content
  leaked into scoring.
- **FR-E7b** The grader's input payload is asserted in tests to contain **only**
  rubric + transcript — no resume fields, no JD fields, no candidate identity.
  This is a structural assertion, so the boundary can't erode silently as the
  code changes.
- **FR-E7c** Candidate identity is withheld from the grader, so the grading step
  is name-blind by construction.

---

## 7. Data Model (indicative)

```
# ── content library: authored offline, human-reviewed, NOT derived from prose ──
competency_taxonomy(competency_id, domain, label)          # the closed vocabulary
    └─< question_bank(competency_id, seniority, neutral_wording, rubric_version)
            └─< bank_rubric_concepts(label, weight, why_it_matters, signals, misconceptions)

# ─────────────────────────── runtime ───────────────────────────
organizations ──< org_members >── users
users ──< resumes ──< resume_versions ──< resume_profiles ──< profile_items(provenance)
organizations ──< job_descriptions ──< jd_versions ──< jd_profiles ──< jd_requirements
organizations ──< postings ──< interview_templates ──< plan_slots
users + postings ──< interview_sessions
    interview_sessions ──< reduction_result(competency_ids[], seniority, domain)  # ← trust boundary output
    interview_sessions ──< session_questions ──< rubric_concepts   # copied from bank at plan time
                              └── framing_text (sanitised, never sent to grader)
                              └── source_profile_item_id (link only — no prose)
        session_questions ──< answers ──< transcript_segments
                          ──< hints
        answers ──< evaluations ──< concept_assessments   (verdict + evidence quote)
    interview_sessions ──< media_assets   (chunked, presigned)
    interview_sessions ──< fit_map_entries (mode C)
    interview_sessions ──< reviews        (human rating + decision + reason)
    interview_sessions ──< integrity_flags
consents · audit_log · outbox_events · usage_costs
```

Notes that matter:
- `evaluations` is **append-only per (rubric_version, model_version)** — scores
  are never mutated in place, so history is defensible.
- `concept_assessments` is the join that makes "what did they miss" a
  first-class queryable fact, not prose buried in a blob.
- `outbox_events` backs reliable async fan-out (grading, notifications,
  webhooks) without losing events on crash.
- `usage_costs` records STT seconds, TTS characters, and LLM tokens per session
  — cost per interview is a first-class metric (§8.3).

---

## 8. Non-Functional Requirements

### 8.1 Conversational latency — `NFR-L`
The interview must *feel* like a conversation. Budgets (p95):

| Step | Target |
|---|---|
| Question audio starts after previous turn ends | ≤ 1.5 s |
| Interim transcript appears after speech starts | ≤ 400 ms |
| Final transcript after silence detected | ≤ 1.0 s |
| Follow-up / next-question decision | ≤ 2.0 s |
| **Total inter-turn gap** | **≤ 3.0 s** |

Grading is explicitly **off** the critical path — it happens after the session.

### 8.2 Scale & reliability — `NFR-S`
- **NFR-S1** The request path is fully async; IO-bound work never blocks a
  worker. Concurrency targets are modest by design (§1.3).
- **NFR-S2** **No completed answer is ever lost**, even on restart mid-session:
  each answer is durably persisted before the turn advances (FR-S4.6), and
  submission is idempotent (FR-S8).
- **NFR-S3** **Graceful shutdown must not kill a live interview.** On `SIGTERM`
  the instance stops accepting *new* sessions, keeps existing WS sessions alive
  until they complete or hit a drain deadline, and only then exits. If the
  deadline is hit, the client is told to reconnect and resumes at the current
  question (FR-S8) rather than losing the session. **This is the reliability
  requirement most specific to this product** — a routine deploy silently
  destroying someone's 25-minute interview is the worst failure mode in the
  system, and it is entirely preventable.
- **NFR-S4** **Vendor failure is contained, not fatal.** Every STT/TTS/LLM call
  has a timeout budget derived from §8.1, retries with jitter, and a **circuit
  breaker**. When the breaker trips: TTS failure → question is shown as text;
  STT failure → typed-answer path (FR-S7); LLM failure → the session still
  completes and grading is queued for later. **An interview never fails because
  a vendor did.**
- **NFR-S5** **Bulkheads:** grading and media-processing use separate queues, so
  a media backlog can never starve grading (and vice versa).
- **NFR-S6** Grading is **at-least-once with idempotent consumers**, dispatched
  via the **outbox** so a crash between commit and enqueue cannot lose a grade.

### 8.3 Cost — `NFR-C`
Self-funded (§1.3), so cost is a **design constraint**, not a dashboard metric.
- **NFR-C1** Per-session cost (STT seconds + TTS characters + LLM tokens) is
  recorded in `usage_costs` and visible to the author. A session whose cost is
  unknown is a bug.
- **NFR-C2** **TTS is cached permanently** per (question, voice, version)
  (FR-V1). With a finite bank this converges to a one-time cost per question,
  approaching zero marginal TTS spend.
- **NFR-C3** Rubrics come from the bank, so **no LLM call is needed to produce a
  question or its standard** at interview time (IR-2). Reduction runs once per
  resume/JD version, not per session.
- **NFR-C4** Remaining variable costs are exactly two: STT on candidate speech,
  and one grading call per answer. Grading is batched per session where possible.
- **NFR-C5** A hard **per-user monthly spend cap** with graceful degradation
  (fall back to text-only mode) rather than a surprise bill.
- **NFR-C6** The STT/TTS/LLM boundary sits behind an adapter interface so a
  cheaper or self-hosted option (e.g. local Whisper for STT) can be swapped in
  without touching the interview logic. This is the single highest-leverage cost
  lever and should not require a refactor to exercise.

### 8.4 Quality metrics — `NFR-Q`
Tracked from day one:
- **AI ↔ human rating agreement** (FR-H6) — the north-star quality metric.
- Grader re-grade variance; golden-set pass rate.
- Hint rate per question (a spike = a bad question, not weak candidates).
- Question skip rate, abandonment rate, mean session duration.
- STT low-confidence rate, **segmented** to catch accent-related disparity.

### 8.5 Accessibility — `NFR-A`
- WCAG 2.2 AA.
- Typed input is a **first-class path**, never a degraded one (FR-S7).
- Live captions for spoken questions; full keyboard operability; screen-reader
  labelling; no reliance on colour alone for coverage chips.
- Accommodation support for extra/unlimited time (FR-S11).

### 8.6 Observability — `NFR-O`
- Structured logs with a request/session correlation id spanning API → worker →
  external calls.
- Per-turn latency histograms against §8.1 budgets.
- Error tracking with session context; an alert on grading-queue depth and on
  golden-set regression.

---

## 9. Security, Privacy & Fairness

### 9.1 Access control — `NFR-SEC`
- Capability-based authorization through one policy layer; every data access is
  org-scoped **and** ownership-checked.
- Candidates can access only their own sessions and reports.
- HR can access only sessions for postings in their org, and only after the
  candidate consented to that org's visibility.
- Media and resume files are reachable only via short-lived signed URLs.
- Full audit log of every view of a candidate's interview (FR-H9).

### 9.2 Data protection — `NFR-P`
This app holds video, voice, and resumes — among the most sensitive PII
categories. Therefore:
- Encryption in transit and at rest; media in a private bucket only.
- **Retention policy per org**, with a hard default (e.g. media 12 months,
  transcripts/scores 24 months) and automatic deletion jobs.
- **Right to deletion:** a candidate deletion request purges media, transcripts,
  resume files and derived profiles, and is verifiable. Aggregate, non-
  identifying metrics may persist.
- Data export for the candidate (their own data, machine-readable).
- Clear disclosure at consent time of every purpose the data is used for.
- Training on candidate data is **off by default** and requires separate,
  explicit, revocable opt-in.

### 9.3 Responsible AI & compliance — `NFR-AI`
- **No automated adverse decision.** Rejection always requires a human
  decision with a reason code (FR-H7).
- Candidates are told, before starting, that AI is used and what it assesses.
- Every score is **explainable**: rubric + concept verdicts + quoted evidence +
  model/rubric version.
- **No demographic inference, ever** — not from name, photo, voice, or video.
- **Score invariance to background (IR-3):** the rating is a function of the
  answers alone. Identical answers earn identical scores whatever the resume
  said, and the grader is name-blind (FR-E7c). This is the strongest
  bias-reduction control in the system, and it is test-enforced (§6.7) rather
  than promised.
- Periodic **adverse-impact review** on outcomes, run on voluntarily-provided,
  separately-stored demographic data where legally permitted; results feed
  rubric revision.
- Re-grade capability so a discovered rubric flaw can be corrected fairly and
  visibly across affected candidates.
- Jurisdictional gating for locales requiring bias audits or specific notices.

### 9.4 Prompt injection — resume/JD are hostile input — `NFR-INJ`
A resume is attacker-controlled text. Sanitising prose is a weak defence; the
**architecture** is the defence — §1.2 reduces hostile free text to a closed
enum before it can reach anything that scores. Layers, outermost first:

- **NFR-INJ1 (architectural — the primary control)** Resume/JD prose is confined
  to the reduction step and **discarded at the trust boundary** (§1.2). No
  component that authors a rubric or produces a score ever receives it. The
  maximum achievable impact of a malicious resume is *the wrong topics were
  selected* — a quality bug, not a scoring compromise.
- **NFR-INJ2** Within the reduction step, prose enters the model only as clearly
  delimited **data**, never in a system/instruction channel.
- **NFR-INJ3** Reduction output is validated against the **closed competency
  taxonomy**; anything not in it is dropped. Free-form model output cannot
  become a topic.
- **NFR-INJ4** Graders receive rubric + transcript only, asserted structurally
  in tests (FR-E7b), and score invariance is enforced by test (FR-E7a).
- **NFR-INJ5** An injection-detection pass flags documents containing
  instruction-like content ("ignore previous instructions", "rate this candidate
  10/10"); flagged docs are quarantined for review. This is defence-in-depth —
  it is **not** relied upon, because it will never be complete.
- **NFR-INJ6** Question **framing** derived from a resume is sanitised,
  length-capped, and never forwarded to the grader (FR-M0c).
- **NFR-INJ7** All rendered candidate/HR-visible text is escaped.

### 9.5 Interview integrity — `NFR-INT`
Signals collected, **as flags for humans, never as automatic penalties**:
window/focus loss, large paste events into the typed path, multiple faces or no
face present, answer latency vs. fluency mismatch suggestive of reading, and
device/session anomalies.
- **NFR-INT1** Flags are advisory, shown with raw evidence, and never alter the
  AI score.
- **NFR-INT2** The product must not over-claim cheating detection. Framing is
  "worth a look", not "this person cheated".
- **NFR-INT3** Candidates are told up front which integrity signals are
  collected.

---

## 10. Key User Journeys

**J1 — Candidate practice (Resume-only)**
Sign up → upload resume → parse completes → review/correct parsed profile →
pick Resume-only, 20 min → consent → device check → interview (voice Q&A, one
hint used on Q4) → completion screen → report: 6/9 core concepts covered, 3
gaps with model sketches → practise again in two weeks and see the delta.

**J2 — Candidate practice for a target role (JD-only)**
Paste the JD of a job they want → JD-only mode → discover which required
competencies they can't yet articulate → targeted study list.

**J3 — HR screening (Resume × JD)**
HR creates a posting + JD → previews and saves the interview template →
invites 30 candidates → 22 complete → queue sorted by AI rating → HR opens the
top 8, reads gaps, jumps into the video at the two answers that matter →
overrides the AI on one candidate (rated higher: the AI missed a strong analogy)
→ advances 5 with reason codes.

**J4 — Calibration**
Over 200 reviews, the platform reports where AI and humans diverge most (e.g.
"system design depth"), pointing at a rubric that over-weights vocabulary →
rubric v2 → affected candidates re-graded and notified.

---

## 11. Delivery Phases

Sequenced for §1.3 (practice-first, showcase-second). **The bank is the
prerequisite for everything** — a beautiful pipeline over a thin bank produces
worthless interviews, so it comes first.

| Phase | Contents | Exit criteria |
|---|---|---|
| **P0 — Bank + core loop** | The **competency taxonomy + a seed question bank** (Appendix C: ~2 domains deep, e.g. Backend/API + Databases, ~40–60 rubrics). Auth, resume upload (presigned) + async parse, JD paste, reduction to selectors, plan generation, **text-first** interview (question shown, typed answer), concept grading, candidate report. Practice mode only. | You can take a real interview on your own resume and the gaps it reports are ones you agree with. That subjective check is the gate — nothing else matters if it fails. |
| **P1 — Voice** | TTS questions + permanent audio cache, streaming STT with interim transcripts, silence detection, barge-in, re-hear, device check, typed fallback, resumability + idempotent submit. | The interview *feels* like a conversation (§8.1 budgets) and a full session's marginal cost is measured and acceptable. |
| **P2 — Bank breadth + progress** | Bank widened across Appendix C domains; difficulty ladders per seniority; cross-session progress tracking (FR-F4); hint ladder tuned from real usage; golden set + drift gate (FR-E6c); score-invariance test (§6.7). | You and your friends can practise any of your target roles, and improvement over time is visible. |
| **P3 — Showcase surfaces** | Video recording + chunked upload, reviewer workspace with transcript↔video sync, peer ratings + AI-vs-human agreement, seeded **public demo session** (read-only, no login) so a visitor can see the product without taking an interview, shareable report link, architecture write-up. | A recruiter or engineer can land on it, understand the thesis in 60 seconds, and click into a real completed interview. |
| **P4 — Optional depth** | Integrity signals, IaC/Terraform, AWS deployment, adapter layer for STT/TTS/LLM vendors, cost dashboard. | Portfolio breadth items; take on demand, not by default. |

**Deliberate ordering notes**
- **Video moved P1 → P3.** It's for *review*, and in a self-practice product you
  are your own reviewer — the transcript already serves that. It's primarily a
  showcase asset, so it ships with the showcase.
- **Text-first in P0 is not a shortcut**, it's the only way to validate the
  rubric/grading quality without voice-pipeline noise confounding every result.
- Each phase ships with tests, structured logs, and an updated spec section. No
  phase is "done" while its NFRs are unverified.

---

## 12. Open Questions

1. ~~**Grading transparency to candidates in official mode**~~ — **largely moot
   at current scope (§1.3):** practice mode is the product and always shows full
   gaps immediately. The rubric-leak concern only matters if this ever becomes a
   real hiring tool; the `none | after_decision | always` setting (FR-F6) is
   already in place for that day.
2. ~~**Question bank vs. always-generate.**~~ **RESOLVED (§1.2, FR-M0):**
   curated **bank of rubrics** keyed by `(competency_id, seniority)`, with
   optional resume-derived **framing** on top. The scoring-isolation boundary
   forces this answer, and it also delivers comparability (FR-P4), lower cost,
   and quality-gateable rubrics. Sizing and authoring process are now answered in
   **Appendix C.5/C.6** (offline LLM-drafted + human-reviewed; seed 40–60 rubrics
   across 2 domains at mid/senior).
3. **Who owns an interview** when a candidate practises and later applies to an
   org — can a practice session be *submitted*? (Consent implications.)
4. **Follow-up depth vs. time budget** — adaptive follow-ups fight a fixed
   duration. Needs an explicit time-allocation policy.
5. **Seniority calibration** — mostly resolved by §1.2: seniority is now an
   explicit **enum selector**, and rubrics are keyed by
   `(competency_id, seniority)`, so a "3/5" is scoped to a level by
   construction. Remaining sub-question: how is seniority *determined* — inferred
   at reduction time, taken from the JD, or set by HR? Recommendation: **JD or HR
   sets it in official mode** (never inferred from the resume, which would
   reintroduce resume influence on the standard); candidate picks it in practice
   mode.
6. **Multi-language** interviews, and whether assessing a non-native speaker in
   English is fair for the role in question.
7. **Live human interviewer hand-off** — is there a "the AI screened, now a
   human joins" mode? Changes the architecture (real-time multi-party) if yes.
8. **Model/vendor strategy** — one provider for STT/TTS/LLM, or best-of-breed
   with an adapter layer? Adapter costs time but avoids lock-in and enables the
   §8.3 cost work.

---

## Appendix A — Assumed Platform

Not a requirement, but the intended build (aligned with existing experience):

- **Backend:** Python, FastAPI, **async-first**; SQLAlchemy 2.0 async; Postgres;
  Alembic. Celery + Redis for parsing/grading/media jobs. WebSockets for the
  live session channel. Transactional **outbox** for reliable event fan-out.
- **Frontend:** Next.js (App Router) with server components for
  read/report/queue pages; TanStack Query for server state; types generated from
  the backend OpenAPI schema.
- **Storage:** object storage with **presigned direct upload** for resumes and
  media (never proxied through the API).
- **Cross-cutting:** capability-based authz policy layer; RFC 7807 problem+json
  errors; idempotency keys on unsafe POSTs; keyset pagination on queues;
  structured JSON logs with correlation ids; metrics + error tracking;
  non-root containers, image scanning in CI; IaC in P3.

**See Appendix D for the actual conventions and the traps behind each one** —
these patterns were built and verified in a prior project, and the gotchas listed
there each cost real debugging time. Reading D before writing code is the single
highest-leverage thing in this document.

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **Trust boundary** | The line (§1.2) where resume/JD prose is reduced to enums and discarded |
| **Reduction** | Turning resume/JD free text into `{competency_ids, seniority, domain}` |
| **Framing vs. standard** | The resume-flavoured wording of a question vs. its bank-authored rubric |
| **Score invariance (IR-3)** | Identical answers ⇒ identical scores, whatever the resume |
| **Rubric** | The expected-concept set attached to a question, keyed by (competency, seniority) |
| **Concept verdict** | `covered` / `partial` / `missing` / `contradicted` for one concept |
| **Fit Map** | Per-JD-competency evidence classification from the resume (Mode C) |
| **Plan / Template** | The pre-generated blueprint of question slots for a session |
| **Raw vs hint-adjusted score** | Score before / after accounting for hints given |
| **Practice vs Official mode** | Candidate-owned self-practice vs org-owned screening |

---

## Appendix C — Competency Taxonomy & Question Bank (CS / Software Engineering)

The closed vocabulary referenced by IR-4. Resume/JD reduction may only emit
`competency_id`s from this list — which is precisely what bounds the damage a
hostile document can do, and what makes two candidates comparable.

**Depth over breadth** (§1.3): this taxonomy is deliberately deep on computer
engineering and software development and covers nothing else.

### C.1 Domains and competencies

| Domain | Competencies (`competency_id` seeds) |
|---|---|
| **cs-fundamentals** | data-structure-choice · complexity-reasoning · recursion-and-dp · sorting-searching-tradeoffs · hashing-and-collisions |
| **os-and-systems** | process-vs-thread · concurrency-primitives · deadlock-and-contention · memory-model-stack-heap · virtual-memory-paging · garbage-collection · scheduling · syscalls-and-io |
| **computer-architecture** | cache-hierarchy-and-locality · pipelining-and-hazards · memory-bandwidth-vs-latency · endianness-and-representation |
| **networking** | tcp-vs-udp · tcp-connection-lifecycle · http-semantics-and-versions · dns-resolution · tls-handshake · load-balancing · websockets-vs-sse-vs-polling · idempotency-of-http-methods |
| **databases** | relational-modelling · normalisation-tradeoffs · indexing-strategy · when-indexes-dont-help · query-planning-and-explain · transactions-and-acid · isolation-levels-and-anomalies · pessimistic-vs-optimistic-locking · offset-vs-keyset-pagination · sql-vs-nosql-tradeoffs · connection-pooling · schema-migration-safety |
| **backend-engineering** | rest-api-design · api-versioning · idempotency-keys · error-contract-design · authentication-mechanisms · authorization-models · session-and-cookie-security · caching-strategies · cache-invalidation-and-stampede · background-jobs-and-queues · at-least-once-and-idempotent-consumers · outbox-pattern · rate-limiting · async-concurrency-model |
| **frontend-engineering** | rendering-strategies-csr-ssr-ssg-isr · server-components · react-render-model · hooks-rules-and-pitfalls · server-vs-client-state · data-fetching-and-invalidation · browser-event-loop · bundle-size-and-code-splitting · core-web-vitals · list-virtualisation · accessibility-fundamentals · type-safety-at-api-boundary |
| **system-design** | requirement-clarification · capacity-estimation · horizontal-vs-vertical-scaling · statelessness-and-session-affinity · consistency-models · cap-tradeoffs · partitioning-and-sharding · replication-and-read-replicas · event-driven-design · backpressure · timeouts-retries-jitter · circuit-breakers · exactly-once-myth · observability-by-design |
| **devops-cloud** | container-images-and-layers · container-security-nonroot · ci-cd-pipeline-design · deployment-strategies · graceful-shutdown-sigterm · logs-metrics-traces · secrets-management · iac-concepts · serverless-vs-containers · cold-starts · cost-model-reasoning |
| **security** | injection-classes · xss-and-output-encoding · csrf-and-samesite · ssrf · broken-access-control-idor · password-storage-hashing · jwt-pitfalls · transport-security · dependency-and-supply-chain · secret-rotation · prompt-injection |
| **testing-and-practice** | test-pyramid-and-boundaries · test-isolation-and-fixtures · flakiness-diagnosis · property-based-testing · mocking-boundaries · debugging-methodology · git-branching-model · rebase-vs-merge · code-review-practice |
| **language-runtime** *(parameterised by language)* | `python`: gil-and-threads · async-await-model · generators-and-iterators · mutable-default-args · dunder-and-data-model · memory-and-refcounting · `js-ts`: event-loop-microtasks · closures-and-scope · prototypes-and-this · promise-semantics · structural-typing-limits · `java`: jvm-memory-and-gc · collections-tradeoffs · concurrency-utilities · `go`: goroutines-and-channels · scheduler-model · `c-cpp`: pointers-and-ownership · undefined-behaviour · raii |
| **ai-llm-engineering** | prompt-design · context-window-management · rag-and-chunking · embeddings-and-similarity · tool-calling · llm-output-evaluation · cost-latency-tradeoffs · llm-prompt-injection-defence |
| **behavioural** *(separate rubric family — see C.4)* | ownership-and-impact · conflict-and-disagreement · failure-and-learning · prioritisation-under-constraint · collaboration-and-mentoring · role-motivation-and-fit |

### C.2 Seniority levels and what actually changes

`fresher · junior · mid · senior` — the *same competency* at a different level
gets a **different rubric**, not merely a harder question:

| Level | The rubric expects |
|---|---|
| **fresher** | The correct mental model of the mechanism. Definitions in own words. No production experience assumed. |
| **junior** | Mechanism + the common failure mode + basic tradeoff awareness. |
| **mid** | Tradeoffs under constraints, "when would you *not* do this", debugging approach, evidence from real work. |
| **senior** | Failure modes at scale, migration/rollout paths, cost and operational consequences, and articulating *what they'd measure* to decide. |

This is why rubrics are keyed `(competency_id, seniority)` (FR-E1a) — a "3/5 on
indexing-strategy" is only meaningful within a level.

### C.3 Worked rubric example (the exact shape to author against)

`competency_id: offset-vs-keyset-pagination` · `seniority: mid`
**Neutral bank wording:** *"An endpoint lists newest-first records and gets slow
when users page deep into the results. What's happening, and how would you fix
it?"*

| # | Concept (`label`) | Weight | `why_it_matters` |
|---|---|---|---|
| 1 | OFFSET makes the DB scan and discard all skipped rows, so cost grows with depth | **core** | This is the actual mechanism; without it the fix is cargo-culted |
| 2 | Fix is to seek by the last-seen ordered key instead of counting rows | **core** | The core idea of keyset/cursor pagination |
| 3 | The ordering key must be unique/total — a tiebreaker is needed or rows repeat or vanish | **core** | The subtle correctness bug most candidates miss |
| 4 | Requires a matching index on the sort key for the seek to be cheap | supporting | Separates "knows the trick" from "knows why it's fast" |
| 5 | Tradeoff: no random page access / no "jump to page 50" | supporting | Shows they understand what they're giving up |
| 6 | Cursors should be opaque and validated (tampering → clean error) | bonus | Senior-flavoured API-design instinct |

**`acceptable_signals` (all count as `covered` — see FR-E2a):** "it has to walk
past all those rows first"; "it counts through everything it's skipping";
"remember where you stopped and start there next time"; "like a bookmark instead
of counting pages". **No candidate ever needs to say the words "keyset" or
"cursor pagination."**

**`common_misconceptions` → `contradicted`:** "add an index and OFFSET gets
fast"; "LIMIT is the slow part"; "cursor pagination lets you jump to any page".

### C.4 Behavioural questions use a different rubric family — `FR-B1`
- **FR-B1a** Behavioural answers are **not** graded by concept coverage. They use
  a `narrative` rubric family assessing: **situation clarity**, **the
  candidate's own action** (vs. the team's), **concrete outcome/evidence**, and
  **reflection** (what they'd do differently).
- **FR-B1b** Graded on **specificity and self-insight**, never on likeability,
  polish, or personality. No inference of traits.
- **FR-B1c** Behavioural slots are a bounded share of any plan (recommended
  ≤ 20%) so a technical practice session stays technical.

### C.5 Bank authoring & governance — `FR-B2`
- **FR-B2a** Bank content is authored **offline** and human-reviewed before it
  ships. LLM-drafting a rubric is fine here — it is an authoring tool, not the
  untrusted runtime path (this is the distinction that keeps IR-2 intact).
- **FR-B2b** A rubric may not ship without: ≥ 2 `core` concepts, ≥ 3
  `acceptable_signals` per core concept, ≥ 2 `common_misconceptions`, and a
  `why_it_matters` line for every concept (it's shown verbatim to the candidate).
- **FR-B2c** **Terminology screen:** no concept `label` may be satisfiable by
  naming a term alone. If a label can be "answered" with one word, it is
  mis-authored.
- **FR-B2d** Bank entries are versioned; editing a shipped rubric creates a new
  version (FR-E1a) and never silently rescores past interviews.
- **FR-B2e** Every rubric added must come with ≥ 1 golden answer (strong) and
  ≥ 1 weak answer for the drift gate (FR-E6c).
- **FR-B2f** Bank health metrics: per-rubric hint rate, average coverage, and
  answer-length distribution. A rubric that everyone or nobody passes is a
  **broken rubric**, not a fact about candidates — flag it for revision.

### C.6 Suggested seed sizing
Start narrow and real, not broad and hollow:
- **P0:** 2 domains the author interviews for (recommended **backend-engineering
  + databases**, which their existing work already covers), `mid` and `senior`
  only → ~40–60 rubrics. Enough for a genuine 30-minute interview.
- **P2:** widen to system-design, devops-cloud, security, one
  `language-runtime`, and frontend-engineering; add `junior`.
- Add competencies **when a real practice session hits a gap** — usage-driven,
  so effort tracks value instead of filling a matrix.

---

## Appendix D — Engineering Patterns & Hard-Won Gotchas

Carried from the prior project (a production blog platform hardened to the same
bar). Every "⚠ trap" below is something that **actually broke** and cost
debugging time. Copy the pattern; don't re-discover the trap.

### D.1 The five non-negotiables
1. **One transaction per request**, owned by the DB dependency — services stage
   work, the seam decides commit/rollback. Services must not commit themselves.
2. **Never trust a pre-check for uniqueness.** The DB constraint is the arbiter;
   catch the violation and translate it (→ 409).
3. **Every error response is problem+json.** One error dialect across the whole
   surface, no ad-hoc `{detail}`.
4. **Authorization is asked, never inspected.** Call `has_perm(user, Perm.X)`;
   never compare role-name strings at a call site.
5. **Migrations run against the DB you think they do.** See D.3 ⚠.

### D.2 Backend / API
| Pattern | Notes & traps |
|---|---|
| **problem+json** (RFC 7807) via one `register_exception_handlers(app)` | ⚠ **`RequestValidationError.errors()` can contain `bytes`** (the raw body) — `json.dumps` chokes and **every 422 turns into a 500**, crashing inside the error handler itself. Wrap the payload in `jsonable_encoder(...)`. This bug is invisible until someone posts a malformed body. |
| **Capability authz**: `Perm` enum + role→perm map built bottom-up so hierarchy is expressed once + policy layer (`has_perm` / `require` / `authorize_owned`) | Create **shared gate instances** at module level (`can_create_story = require(Perm.X)`) — FastAPI `dependency_overrides` keys on object identity, so inline `Depends(require(...))` is un-overridable in tests. |
| **Idempotency keys** on unsafe POSTs (Redis `SET NX`) | Essential here for answer submission (FR-S8) — a retried submit must never double-record. |
| **API versioning** under `/api/v1` | ⚠ Moving routers **breaks the auth cookie `path`** — a refresh cookie scoped to `/auth` stops being sent to `/api/v1/auth`. Also breaks any *browser-navigation* URL (OAuth start links) and any hardcoded path in e2e tests. Grep for the old prefix everywhere, not just in the API client. |
| **Keyset pagination** for any growing list | Compound key `(created_at, id)` — the id tiebreaker is what makes ordering *total*; without it rows repeat or vanish across pages. |
| **ETag + `If-None-Match` → 304** on read endpoints | Use `private, no-cache` when the body varies per viewer (§8) — allows revalidation, forbids shared-cache reuse. |
| **Cache-aside with explicit invalidation** | Only cache **anonymous** responses; per-user flags in a shared cache key leak state between users. |

### D.3 Data & migrations
| Pattern | Notes & traps |
|---|---|
| **Unique constraint as arbiter** → catch `IntegrityError` → 409 | Pair with a concurrency test that actually races two threads (§6.7 style). |
| **Optimistic locking** via a `version_id_col` → catch `StaleDataError` → 409 "refresh and retry" | Right for interview sessions where two tabs could submit. |
| **`CREATE INDEX CONCURRENTLY`** inside `op.get_context().autocommit_block()` | Plain `CREATE INDEX` locks writes for the build. Concurrently can't run in a transaction — the autocommit block is the Alembic-sanctioned escape. |
| **Generated columns** (e.g. tsvector) live in migrations, not the ORM model | ⚠ **The test fixture's `create_all()` won't create them**, so the feature is silently *untestable* and 500s only in tests. Mirror migration-only DDL into the test schema fixture. We shipped a full-text search that no test could ever have exercised. |
| **Pin the migration DB URL per environment** | ⚠ **Near-miss: local `docker compose` migrations ran against PRODUCTION** because `MIGRATION_DATABASE_URL` fell through to the prod value in `.env`. Pin it explicitly in compose for **every** service that can run migrations. Verify before you trust it. |

### D.4 Async & concurrency
- **Dual engines on purpose:** async engine for the request path, **sync engine
  retained** for Celery workers, log handlers, and seed scripts. They coexist
  fine; FastAPI runs sync routes in a threadpool.
- **The unit-of-work dependency** yields the session, `await commit()` on
  success, `rollback()` on exception.
- ⚠ **No lazy IO in async.** Any relationship touched later must be eager-loaded
  (`joinedload`/`selectinload`) or you get `MissingGreenlet` — *at runtime, on
  that code path only*. The one that bit us: `has_perm` reads `user.role`, so the
  **async auth dependency must `joinedload(User.role)`**. It manifests as a 500
  only for authenticated users on routes that check permissions.
- ⚠ **Commit-then-enqueue ordering.** A write that enqueues background work must
  commit *before* the job is queued, or the worker races an invisible row. Under
  a commit-at-the-seam UoW the commit happens *after* the service returns — so
  either keep such writes sync, or use an **outbox** (preferred here, since
  grading and media jobs both fire off writes).
- **Applied to this project:** the turn loop is write-heavy (answers, hints,
  transcript segments). Use the **outbox** rather than the "async reads / sync
  writes" split — grading dispatch must be reliable, and an outbox gives that
  without splitting the codebase.

### D.5 Testing
| Pattern | Notes & traps |
|---|---|
| **Isolation**: private schema per session + connection-level transaction + SAVEPOINT rolled back per test | ⚠ `search_path` is **per-connection**, so set it in a pool `connect` event — setting it once on one connection isolates only that connection. |
| **Sync→async session adapter** for testing async routes | Present the sync test session behind the async API (`await execute/get/commit`). Async endpoints then run *inside* the test transaction — no second engine, no lost isolation. This is the single trick that made async code testable. |
| **Async dependency overrides are separate objects** | ⚠ Overriding `get_current_user_optional` does **not** override `get_current_user_optional_async`. An async route silently sees an anonymous user and the test fails somewhere unrelated. |
| **Property-based tests** (hypothesis) for pure logic | Codec round-trips, parsers, cursor encode/decode. |
| **Fuzz for "never a 5xx"** across the public surface | Found two real bugs in one run. ⚠ Constrain generated path segments to URL-safe charsets — raw control characters are rejected by the HTTP *client*, which is a false positive, not a server defect. |
| **Matrix tests with an independent expectation table** | For authz (and here, rubric/permission behaviour): hand-write the expected grid rather than importing the implementation's map, or the test proves nothing. |
| **Real-thread concurrency tests** | Own session per thread + a `Barrier` to line them up. ⚠ Those sessions need an explicit `SET search_path` to the test schema. |

### D.6 Frontend
- **Server Components for read/report/queue pages**; extract interactive parts
  into a `*Client.tsx` island. Add `generateMetadata`, `sitemap.ts`, `robots.ts`.
- **TanStack Query owns all server state.** Centralise query keys; mutations
  invalidate precisely. Deletes the useEffect/loading/error/cancelled bug family.
- **Types generated from OpenAPI** (`openapi-typescript`), consumed by services —
  so schema drift becomes a **compile error**.
  ⚠ Adopting generated types will *surface existing drift* — ours revealed four
  fields the UI read that the API never returned (silently `undefined` in prod).
  Budget time for the fallout; that fallout is the payoff.
  ⚠ Regenerating from inside a container must target the **service name**
  (`http://backend:8080/openapi.json`), not `localhost`.
- **Nullability is real.** Generated types mark optional relations optional —
  use `?.` and `?? []` rather than casting the honesty away.

### D.7 Ops & CI
- **Non-root container** (`groupadd`/`useradd` + `chown` + `USER`), `HEALTHCHECK`,
  multi-stage build. ⚠ Services sharing an image but with no HTTP port (workers)
  must disable the healthcheck. ⚠ After adding `USER`, `docker cp` writes
  root-owned files the app user can't delete — clean up as root.
- **Image scanning (Trivy) report-only in CI** (`--exit-code 0` +
  `continue-on-error`). A CVE disclosed upstream should not redden an unrelated
  PR. Flip to enforcing when the baseline is clean.
- **Dependency hygiene:** pin everything; **dry-run resolve before rebuilding**.
  ⚠ A single unrelated package can cap a security fix — a metrics plugin pinned
  `starlette<1.0` and silently blocked a starlette CVE upgrade. When a bump is
  refused, find the *capper*, don't give up on the fix.
- **Structured JSON logs in prod / human-readable in dev**, request-id via
  contextvar propagated through middleware → services → tasks.

### D.8 LLM-specific patterns (new for this project)
These have no precedent in the prior project — treat them as the areas where
you'll invent, and therefore where discipline matters most.
- **Schema-validate every model output**; retry on malformed, then quarantine
  for human review. Never "best-effort parse" a score.
- **Pin model + prompt + rubric versions on every stored evaluation** so any
  score is reproducible and explainable months later (FR-E6b).
- **Golden set + drift gate**: a prompt or model change must re-score a fixed set
  of answers within tolerance or it doesn't ship (FR-E6c).
- **Treat all user-supplied documents as hostile input** and reduce them to
  validated enums before they reach anything that decides an outcome (§1.2).
  This is the LLM-era equivalent of "never build SQL by string concatenation".
- **Cost is a first-class metric** — record tokens/seconds per session from day
  one (§8.3); retrofitting attribution is painful.

### D.9 What NOT to copy from the prior project
Judgement matters more than consistency:
- **Async reads / sync writes split** — that was the right compromise there
  (Celery-shared helpers on the write path). Here, use the **outbox** instead and
  keep one coherent async model.
- **Multi-tenant org scoping everywhere** — real there, over-engineering at
  "me and my friends" scale (§1.3). Keep an `organization_id` column so it's
  *possible* later; don't build the org-management product now.
- **Horizontal-scale machinery** (replicas, sharding, queue autoscaling) —
  explicitly out of scope (§2.2). One Postgres and one worker is the *correct*
  architecture at this size, and saying so confidently is itself a senior signal.
- **Heavy compliance apparatus** (bias audits, jurisdictional gating) — the
  *mechanisms* (IR-3, name-blind grading, consent, audit log) carry over; the
  statistical reporting needs population volume that won't exist.

---

## Appendix E — TECH_TARGETS Coverage Map

Every item from `TECH_TARGETS.md` mapped onto this project. Three honest depths:

- **BUILD** — real feature, real value here.
- **SLICE** — a small genuine implementation that proves the concept without
  inventing scale you don't have.
- **VOCAB** — building it here would be theatre. Instead write a short **ADR**
  (`docs/adr/NNN-*.md`) recording the decision and *why it was rejected at this
  scale*. A reasoned rejection is stronger portfolio evidence than a fake
  implementation, and it's exactly what the interview question is really testing.

### E.1 Tier 1 — foundational

| # | Target | How it lands here | Depth | Phase |
|---|---|---|---|---|
| 1 | Async Python & concurrency | Async request path; the live turn loop is IO-bound fan-out (STT/TTS/LLM). `asyncio.gather` for parallel prefetch (next question's audio while current answer records). | BUILD | P0/P1 |
| 2 | Transactions, UoW, concurrency control | One txn/request; `IntegrityError`→409; optimistic lock on session/answer writes; **the two-thread race test** (§6.7 style) | BUILD | P0 |
| 3 | SQL beyond ORM | **Window functions** for progress-over-time (competency score trend, `LAG` for delta vs last session); **CTEs** for the report rollup; **FTS** over the question bank; **JSONB** for rubric concept payloads + GIN; **composite/partial indexes**; **`EXPLAIN ANALYZE`** on the report query with the plan recorded in an ADR | BUILD | P0/P2 |
| 4 | Rendering strategies & RSC | Report + review pages as Server Components; `generateMetadata`; public demo page static/ISR; interview room is a client island | BUILD | P0/P3 |
| 5 | Server-state (TanStack) | All server state; mutations invalidate; **optimistic update with rollback** on "mark hint used"/rating; **infinite query** on session history | BUILD | P0/P2 |
| 6 | Runtime validation at trust boundaries | Two boundaries, not one: **OpenAPI codegen** for the API↔frontend contract, **plus runtime schema validation (zod/pydantic) on every LLM output** — the LLM boundary is where types are genuinely fiction (FR-E6a) | BUILD | P0 |
| 7 | Redis, queues, WebSockets | Redis (cache, idempotency, rate limit, TTS cache index); Celery (parse, grade, media); WS for the live session channel | BUILD | P0/P1 |

### E.2 Tier 2 — senior differentiators

| # | Target | How it lands here | Depth | Phase |
|---|---|---|---|---|
| 8 | HTTP & web-platform depth | Cookie attributes done properly (`HttpOnly`/`Secure`/`SameSite`/`Path` — and §D.2's versioning trap); **CORS with credentials** for the split origin; **ETag/304** (§8); **CSP** headers; know the TLS handshake + HTTP/2 multiplexing shape for the ADR | BUILD | P0/P1 |
| 9 | API design maturity | `/api/v1`, problem+json, idempotency keys, cursor contracts, **HMAC-signed outbound webhook** ("interview.graded" → a test receiver, retried via the queue) | BUILD | P0/P3 |
| 10 | Authz as a system | `Perm` enum + policy layer + **matrix test**; **OAuth2 authorization-code + PKCE** done properly (not imitated); explicit **CSRF posture** documented for the cookie-auth paths | BUILD | P0 |
| 11 | Observability | Structured JSON logs + request/session correlation id through API→worker→vendor; **p95 per route**; **the turn-latency histogram vs §8.1 budgets**; error tracking; **one real alert** (grading queue depth) | BUILD | P1 |
| 12 | Docker & deploy depth | Non-root, `HEALTHCHECK`, multi-stage, Trivy; **SIGTERM → drain** matters unusually here: a deploy must not kill a live interview (NFR-S3) | BUILD | P1 |
| 13 | Testing depth | **hypothesis** (property) + **fuzz** (never-5xx) + **locust** (p95 @ RPS, recorded); **contract testing against our own OpenAPI**; the flake lesson: *never assert transient states against instant mocks* | BUILD | P0/P2 |
| 14 | Postgres operations | **Pooled connection string** (serverless×Postgres is the classic incident); `CREATE INDEX CONCURRENTLY`; **run one PITR restore drill and record the time** — cheap, and "I have actually restored a database" is a true sentence few can say; vacuum/bloat basics | BUILD | P1 |

### E.3 Tier 3 — vocabulary, with the slices worth actually building

TECH_TARGETS says whiteboard-only. But several have a *genuine* need in this
app — those get a real slice; the rest get an ADR.

| # | Target | Verdict here |
|---|---|---|
| 15 | Event-driven patterns | **BUILD the outbox** (grading dispatch must not be lost) + **idempotent consumers** (at-least-once is what you actually get). Grading pipeline *is* a lived saga-lite example: interview→grade→notify with compensation on failure. ADR for exactly-once mythology. |
| 16 | Failure handling | **SLICE, and genuinely needed:** vendor calls (STT/TTS/LLM) get **timeout budgets** derived from §8.1, **retries with jitter**, and a **circuit breaker** that trips to text-only mode (NFR-S4). **Bulkhead:** separate queues for grading vs media so a media backlog can't starve grading. Thundering-herd → jittered retry on reconnect. |
| 17 | Scale vocabulary | **VOCAB (ADR).** Read replicas, partitioning/sharding, CQRS: wrong problems at tens of users (§2.2). *One* exception worth a slice: the progress/report **read model** is a legitimate CQRS-lite — a precomputed projection rather than recomputing rollups per page load. **Cache stampede** protection on the TTS cache is a real slice (single-flight on first synth). |
| 18 | Frontend perf & a11y | **BUILD:** a11y is a *hard requirement* here, not polish — typed path is first-class, live captions, focus management in the interview room, full keyboard operability (§8.5). **SLICE:** bundle analysis + code-splitting the interview room; Core Web Vitals on the public/report pages; **list virtualisation** only if a transcript gets long enough to need it. |
| 19 | Security fluency | **BUILD:** OWASP classes you now own end-to-end + **CSP**, **secrets rotation** (you have lived this once — do it deliberately this time), **supply-chain** (pinned deps, lockfile audit + Trivy in CI). Plus the modern one this app forces: **prompt injection** (§9.4) — arguably the most current security story you can tell. |
| 20 | IaC (Terraform) | **BUILD in P4.** One afternoon, disproportionate resume value; the stack is small enough to be genuinely expressible. |

### E.4 Tier 2.5 — cloud

| # | Target | How it lands here | Depth | Phase |
|---|---|---|---|---|
| 21 | Cloud mental model | **Presigned direct-to-storage upload is core to this app** (resumes + video chunks) — the exact pattern TECH_TARGETS flagged as "build it once in v2"; **service identity/IAM least-privilege** audit of what the runtime SA can touch; **Secret Manager** for every credential; public vs private networking; **pooled DB string**; cloud-native logs/metrics; **cost model literacy is forced by §8.3** (you'll know exactly which line item explodes: STT, then LLM) | BUILD | P1/P3 |
| 22 | AWS translation layer | **P4, optional:** redeploy to App Runner/ECS Fargate + RDS-or-Neon + **S3 presigned uploads** + CloudWatch, provisioned by Terraform (doubles #20). Makes "deployed on GCP and AWS, IaC via Terraform" a true sentence. Skip the cert grind. | BUILD | P4 |

### E.5 Deliberately excluded (from TECH_TARGETS' own list)
- **Kubernetes** — concepts in an afternoon of reading; running it here is cosplay.
- **Microservices** — the monolith is architecturally correct at this scale, and
  knowing *why* is the senior answer.
- **GraphQL** — only if a target company uses it.
- **WebRTC** — ⚠ worth stating explicitly because this app has video: recording
  is `MediaRecorder` → **chunked presigned upload** (FR-M2), *not* a peer
  connection. WebRTC would only be needed for a **live** human-joins-the-call
  mode (§12 Q7), which is out of scope. Don't reach for it by reflex.

### E.6 Suggested ADR set (the deliverable for every VOCAB item)
Short docs, 1 page each — these are portfolio artifacts in their own right:
`001-no-kubernetes` · `002-monolith-over-microservices` ·
`003-no-read-replicas-or-sharding-at-this-scale` ·
`004-cqrs-lite-only-for-the-progress-read-model` ·
`005-at-least-once-not-exactly-once` ·
`006-schemathesis-rejected-dependency-conflict` ·
`007-no-affect-scoring-from-video` · `008-scoring-isolation-boundary` (§1.2) ·
`009-webrtc-not-required-for-recorded-video`.
