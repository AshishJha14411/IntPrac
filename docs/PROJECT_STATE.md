# Project state — 11 Aug 2026

Written at the end of a long working session, for whoever picks this up next
(including me, cold). Everything here is either not recorded anywhere else, or
is the one-paragraph version of something recorded at length elsewhere.

Facts that live in code — how synthesis works, why the grader is sealed, what
things cost — are in the code, the README and `REQUIREMENTS_SPEC.md`, and are
not repeated here. This file is for the things a fresh reader would otherwise
have to rediscover.

---

## Where it stands

**Live in production**, `interview-api-00006-bl7`, image tag `ffa7a62`:

- Plan synthesis. One model call reads the resume and/or JD and writes the whole
  interview — questions, rubrics, follow-ups — for any profession. Verified
  against clinical trial management, marketing, Veeva CRM and engineering
  management resumes.
- Resume × JD (`combined`) mode, reachable from the UI for the first time.
- The mechanism-focused prompt (ask what breaks, not how you approached it).

`dev` is one commit ahead: `bb46104`, the README cost section. Docs only.

**Deployment shape:** GitHub Actions → Cloud Run, keyless via Workload Identity,
**zero repository secrets** — the addresses are literals in `deploy.yml` and the
real credentials are in Secret Manager. `--min-instances 0`, no worker, no beat;
retention and the outbox sweep run as Cloud Run Jobs on Cloud Scheduler.
Frontend is deployed by Vercel's own Git integration, not by the workflow.

---

## Do this first

**Rotate four credentials.** All were pasted into a chat transcript during
setup, and the repo is public:

| what | where |
|---|---|
| Neon database password | Neon console → reset, then `bash scripts/gcp-bootstrap.sh secrets` |
| Gemini API key | AI Studio / `gcloud services api-keys` in `promptopia-428409-h3` |
| Google OAuth client secret | Cloud console, project `gen-lang-client-0452867537` |
| Upstash Redis token | Upstash console |

`gcp-bootstrap.sh secrets` is idempotent and only writes a new secret version
when the value actually changed, so re-running it after each rotation is safe.

**Check the OAuth consent screen's publishing status.** The client lives in the
**QuillnCode** project (`gen-lang-client-0452867537`), not the project the app
runs in. If it is still in *Testing*, only listed test users can sign in, capped
at 100 — the single thing most likely to stop real people using the app.

---

## Open problems

**The intermittent smoke failure.** CI's `smoke` job has failed twice with a 409
in the turn loop and passed every other run. Never reproduced locally across
six consecutive attempts under CI's exact configuration. **Not fixed** — only
instrumented: every call now goes through `req()` in `scripts/smoke.sh`, which
prints method, path, status and the problem+json body, and emits a `::error::`
annotation readable through the REST API without a token. The next occurrence
will say what it was.

**Combined mode leans on the resume.** Given a backend CV and a platform/SLO job
description, all six questions came from the CV. The prompt asks for the
*overlap* and to probe whether the candidate could reach what the role needs;
that half is only partly followed. Prompt tuning, not a bug, but do not rely on
combined mode to test role fit yet.

**Synthesis output varies run to run.** The same Veeva resume produced domain
`veeva-crm-development` on one run and `crm-development` on the next. Harmless
today because the domain is only a label, but nothing pins it. Some questions
also come back long and compound.

**Nobody has spoken into the app.** Voice is built — Web Speech plus Vosk WASM
behind one interface (ADR 011) — and has never been exercised by a human in
Chrome or Firefox, nor has the 40 MB Vosk first load been timed on a real
connection.

**Nobody outside software has read a generated rubric.** The clinical and
marketing output looks structurally right and reads plausibly, but no
practitioner in those fields has checked it. This is the one quality gate no
test replaces, and it is the reason the regulated-domain wording in the prompt
is a request rather than a guarantee.

---

## Smaller, known, not done

- **`/health/ready` does not report which commit is running.** The image tag is
  the git SHA, so the answer exists — but only in GCP, not from the app. Two
  lines to fix and worth it the first time a user reports something odd.
- **`usage_costs` has no purpose column.** Input vs output tokens are recorded,
  not which call they came from. The authoring/grading split in the README works
  only because authoring is written with a null `session_id`; that is incidental
  and a third kind of call would land in the wrong bucket unnoticed.
- **mypy is `continue-on-error` in CI** with ~23 errors outstanding.
- **`gaps.md`** — all 15 P0s are closed. The 23 P1s and the P2s are not.
- **A spare GCP project** — `gen-lang-client-0064902591`, auto-created by AI
  Studio, now holds nothing. Safe to delete; 30-day recovery window. Do **not**
  delete `gen-lang-client-0452867537` (QuillnCode): it serves a live blog and
  owns the OAuth client this app uses.

---

## Decisions that were made deliberately

Recorded because each one looks like an oversight from the outside.

**The bank is a cache, not a catalogue.** Questions are generated per candidate
and persisted; the authored bank is preferred when it covers the topic
(`rubric_version` tie-break) but no longer limits what can be asked. This
reversed §1.3's "breadth is explicitly a non-goal", and the spec says so.

**Cross-candidate comparability was given up.** Two people no longer answer the
same questions, so the report is a personal development signal, not a ranking.
IR-3 now holds only in the narrow form the tests assert: same rubric plus same
answer gives the same verdict. IR-1 — the grader never sees a document — is
untouched and is now the load-bearing guarantee.

**No field picker.** Domain is inferred from the documents. Revisit if inference
proves wrong often; the failure is invisible until the questions are wrong.

**No self-hosted model.** A Cloud Run L4 GPU is ~$0.71/hour idle and 8B CPU
inference would take 5–25 minutes per rubric. At ~$0.003 per cached-forever
rubric, hosting costs more and is slower, and is weakest exactly where domain
accuracy matters.

**No penalty for managers.** Tested: an engineering manager resume gets asked
what breaks in their error-budget policy under pressure, *and* two hard
questions pulled from their older hands-on work. Hard on merit, which produces a
report that explains itself. Rigging it would produce a number that lies.

**No sensitive-domain blocklist.** There was one; it refused any domain matching
"clinical" and fell back to the bank, so a Clinical Trial Manager was asked
about API versioning — the exact bug the feature exists to fix, reintroduced by
the guard. Too coarse, and it failed in the wrong direction. What holds the line
now is the prompt (ask about process and judgement in regulated fields, never
invent facts) plus `validate_question`.

---

## The failure mode this project keeps hitting

Four times now, something was **correct in the code and absent from the running
system**:

1. `CELERY_TASK_ALWAYS_EAGER` set in a cloud console and nowhere in the repo.
2. `LLM_GRADER_MODEL`'s cheap default in `config.py`, silently overridden by a
   literal in `docker-compose.yml`, so the measured saving never shipped.
3. `app/entrypoints/jobs.py` written specifically so retention would survive
   workerless mode — and never invoked by anything, so the six-month window was
   enforced by a docstring.
4. `--service-account` omitted from Cloud Run deploys, so containers ran as the
   project's compute account: `roles/editor` on everything, and still unable to
   read Secret Manager.

Each now has a test in `tests/unit/test_scheduled_jobs_are_deployed.py`, which
asserts properties of `deploy.yml` itself. When adding infrastructure, assume
the same class of bug and write the assertion.

A related habit: **a guard that has never failed has not been tested.** Two
guards written this session passed against the very bug they were written to
catch — one searched step text and was satisfied by a commented-out line, one
used `curl -fsS … || true` so a 500 became an empty body. Mutate the thing, watch
the test fail, then keep it.

---

## Verifying anything here

```bash
docker compose run --rm migrate          # then seed
docker compose --profile tools run --rm test        # 375 pass
./scripts/smoke.sh                                  # 23 checks, needs a running stack
API=https://interview-api-379068176383.asia-south1.run.app/api/v1 \
  bash scripts/check-google-oauth.sh                # asks Google, no browser

# what is actually serving
gcloud run services describe interview-api --region=asia-south1 \
  --format="value(status.latestReadyRevisionName, spec.template.spec.containers[0].image)"
```

The image tag is the git commit SHA. `git log -1 <tag>` names the commit.
