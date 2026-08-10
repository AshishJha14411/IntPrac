# AI Interview Platform

An interview platform that scores **understanding, not vocabulary**. A
candidate who explains the right mechanism in plain words scores higher than
one who recites the correct term with the wrong mental model.

Interviews are **spoken** — the question is read aloud, the answer is dictated,
and the transcript appears as you talk, in **every** browser. **Typing sits
next to it as a peer, not a fallback**, switchable mid-answer. That is
structural rather than a courtesy: grading consumes the transcript and nothing
else (FR-V5), so there is no mechanism by which speaking and typing could score
differently. See [ADR 011](docs/adr/011-voice-in-the-browser.md) — the whole
pipeline runs client-side, so it costs nothing and this app never stores a byte
of audio.

Full requirements: [`REQUIREMENTS_SPEC.md`](REQUIREMENTS_SPEC.md).
Design decisions and their rejections: [`docs/adr/`](docs/adr/).

---

## The one architectural idea

> **The resume and JD decide WHAT IS ASKED. Only the interview decides THE RATING.**

```
resume text ─┐
             ├─►  [ REDUCTION ]  ─►  {competency_ids[], seniority, domain}  ─► everything downstream
JD text ─────┘   (schema-validated,          ▲
                  closed taxonomy)           │
                                    ═════════╪═════════  TRUST BOUNDARY
                  free text is DISCARDED here; nothing past this
                  line ever receives resume or JD prose
```

Where this lives in the code:

| Concern | File |
|---|---|
| The boundary itself | [`app/services/reduction.py`](backend/app/services/reduction.py) |
| The only row that crosses it | `ReductionResult` in [`app/models/interview.py`](backend/app/models/interview.py) |
| The grader's whitelist-only payload | [`app/llm/prompts/grading.py`](backend/app/llm/prompts/grading.py) |
| The tests that make it a guarantee | [`tests/unit/test_score_invariance.py`](backend/tests/unit/test_score_invariance.py) |

`build_grading_payload()` takes exactly three arguments — bank wording, rubric
concepts, transcript — and has no `**kwargs`. There is no parameter through
which a resume could reach a score, so IR-3 holds by construction rather than
by discipline. The test asserts that signature, so it fails the moment someone
adds one.

---

## Run it

Everything is in compose; no host toolchain is needed beyond Docker.

```bash
cp .env.example .env                      # optional: add GEMINI_API_KEY
docker compose up -d --build              # api, worker, beat, web, postgres, redis, minio
docker compose run --rm migrate           # apply migrations
docker compose run --rm seed              # taxonomy + question bank
./scripts/smoke.sh                        # end-to-end check (11 assertions)
```

- Web: <http://localhost:3000>
- API docs: <http://localhost:8080/docs>
- MinIO console: <http://localhost:9001>

### Running it without a worker (ADR 010)

A Celery worker is a *polling* consumer, so a scale-to-zero host has nothing to
scale it up on and it has to be pinned always-on — one CPU billed around the
clock, plus beat's, for a system that is idle most of the day. Every other
component here scales to zero, so those two would be the entire bill. §8.3
treats cost as a design constraint, so there is a second mode:

```bash
CELERY_TASK_ALWAYS_EAGER=true docker compose up -d --build api web
./scripts/smoke.sh                        # the same 18 checks must pass
python -m app.entrypoints.jobs retention  # beat is gone; a scheduler runs this
```

Tasks run inline and **the request drains its own outbox once it has
committed** — the flag alone would not be enough here, because nothing in this
codebase calls `.delay()` directly. `GET /api/v1/health/ready` reports
`"dispatch": "inline" | "worker"` so which mode a deployed instance is actually
in is a `curl`, not a console dig. Local dev defaults to the broker path
deliberately: it is the mode with the stronger guarantees, so bugs surface
there rather than in the cheap one.

Without `GEMINI_API_KEY` the app runs on a **deterministic stub grader** and
says so loudly at boot. The stub scores by lexical overlap against each
rubric's own `acceptable_signals` — crude, but honest about being crude, and it
exercises the entire pipeline (schema validation, evidence enforcement, hint
adjustment, rollups) without spending money or introducing nondeterminism.

### Tests

```bash
docker compose --profile tools run --rm test          # 260 tests
docker compose --profile tools run --rm test pytest -m invariance   # the IR-3 gate
./scripts/smoke.sh                                    # 18 checks against a running stack
```

`smoke.sh` covers both intake paths: JD paste → async parse → plan → consent →
turn loop → grading → report, and resume presigned-upload → object storage →
parse → resume-only mode with framing.

---

## What is built

Phase **P0** of §11, complete and verified end to end.

| Area | State |
|---|---|
| Auth | Email/password, argon2id, rotating refresh tokens with **reuse detection** (family revoked on replay) |
| Authorization | Capability enum + one policy layer; matrix-tested against a hand-written grid |
| Resume intake | Presigned direct-to-storage upload, async parse, versioned profiles with **provenance spans**, correction overlay |
| JD intake | Paste + async parse; thin JDs are flagged, not silently accepted |
| Reduction | The trust boundary: prose → validated closed-taxonomy selectors |
| Planning | Deterministic, reviewable before the session; **no LLM call**, rubrics copied from the bank and frozen |
| Interview | Turn loop with **spoken or typed** answers (equal peers), question read aloud, consent gate, idempotent submit, 3-rung hint ladder, follow-ups, skip, resumability |
| Voice | Streaming STT with per-segment timings + confidence, **two engines behind one interface**: the browser's native recogniser, or a Vosk model running on the candidate's own device (Firefox, or anyone who wants their audio to stay local). Low-confidence spans flagged for the candidate to correct **before** anything is graded; device check; £0 and no audio stored |
| Grading | Async via transactional outbox → Celery; schema-validated concept verdicts with **mandatory evidence quotes**; quarantine on malformed output |
| Report | Covered / partial / missed per concept with `why_it_matters` verbatim, raw **and** hint-adjusted scores, top-3 improvements, cost |
| Content bank | 129 competencies; **52 authored rubrics** — every competency in both P0 domains (12 databases + 14 backend) at mid **and** senior — 277 concepts, 104 golden answers |

The bank sits in the middle of Appendix C.6's 40–60 target. Every rubric passes
the authoring bar, enforced at seed time and in CI: ≥2 core concepts, ≥3
plain-language `acceptable_signals` per core concept, ≥2 misconceptions, a
`why_it_matters` line on every concept, an L2 signpost that doesn't quote a
signal, and a strong + weak golden answer.

### Known gaps, stated plainly

- **Voice is built, but in the browser.** Spoken questions and streaming
  dictation with per-segment timings and confidence (FR-V1–V6) all run client
  side, so there is **no audio or video artifact** — which means FR-M media
  recording and HR's "jump to this answer" playback (FR-H4) are still open. The
  timings are stored and correct; there is just nothing yet to seek within.
  [ADR 011](docs/adr/011-voice-in-the-browser.md) has the trade-offs, including
  the accent-robustness one.
- **The reviewer workspace (P3) is not built** — a later phase in §11, not
  unfinished P0. `Posting` and `FitMapEntry` exist and the enums are in place.
- **Email verification is modelled but not sent.** FR-A2 gates *official* mode,
  which is P3; practice mode does not require it.
- **The taxonomy lists 129 competencies but only the two P0 domains are
  authored.** That is deliberate (Appendix C.6: start narrow and real). The
  other domains are reachable by reduction only once someone writes their
  rubrics — a competency with no authored rubric is skipped rather than asked
  badly.

---

## Layout

```
backend/
  app/
    content/      taxonomy + authored question bank + the authoring validator
    core/         config, logging, problem+json, security, idempotency, shutdown
    db/           engines and the unit-of-work seam
    domain/       enums and the session state machine
    models/       SQLAlchemy models (content library above the boundary, runtime below)
    authz/        Perm enum + the single policy layer
    api/v1/       routes
    services/     reduction (the boundary), planning, interview, grading, report
    llm/          the vendor-agnostic adapter, schemas, prompts, deterministic stub
    workers/      celery app, outbox relay, grading, parsing, retention
  tests/          unit / integration, incl. the IR-3 gate and a real-thread race test
frontend/         Next.js App Router: RSC report, client-island interview room
docs/adr/         decisions, including the ones deliberately rejected
scripts/smoke.sh  end-to-end verification against a running stack
```

---

## Conventions worth knowing before you edit

These are load-bearing. Each one exists because breaking it cost real debugging
time (Appendix D).

1. **One transaction per request, owned by the DB dependency.** Services stage
   work; the seam in `db/session.py` decides commit or rollback. Nothing under
   `api/` calls `commit()`.
2. **Never pre-check for uniqueness.** The database constraint is the arbiter —
   catch `IntegrityError` and translate it to a 409.
3. **Every error is problem+json.** One dialect, no ad-hoc `{"detail": ...}`.
4. **Authorization is asked, never inspected.** `has_perm(principal, Perm.X)`;
   no role-name string comparisons at call sites.
5. **Migrations run against the database you think they do.** `env.py` reads one
   explicit variable, prints the masked target, and refuses to guess.
6. **No lazy IO on the async path.** Eager-load anything you touch after an
   `await`, or you get `MissingGreenlet` at runtime on that path only. The test
   harness *cannot* catch this — see below.

### The one thing the test suite cannot tell you

The pytest harness presents a **sync** session behind the async API, which is
what makes async endpoints testable inside a rolled-back transaction. The
trade-off is that there is no greenlet boundary, so lazy relationship IO passes
in tests and 500s in production. Two such bugs shipped past a fully green suite
while building this, and both were caught by `./scripts/smoke.sh`.

Run it before merging anything that touches the async request path.
