# Working in this repo

Read `REQUIREMENTS_SPEC.md` §1.2 before touching anything that produces a
score. The rest of this file assumes you have.

## Commands

```bash
docker compose up -d --build                        # full stack
docker compose run --rm migrate                     # alembic upgrade head
docker compose run --rm seed                        # taxonomy + question bank
docker compose --profile tools run --rm test        # pytest (260)
docker compose run --rm --no-deps api ruff check .  # lint
./scripts/smoke.sh                                  # end-to-end, needs a running stack

CELERY_TASK_ALWAYS_EAGER=true docker compose up -d --build api web   # workerless
```

Generate a migration (needs the source mounted, so use the `api` service):

```bash
docker compose run --rm --no-deps --entrypoint sh api -c \
  'alembic revision --autogenerate -m "what changed"'
```

## Non-negotiables

1. **One transaction per request**, owned by `db/session.py`. Services stage
   work; the seam commits. Nothing under `api/` calls `commit()`.
2. **The DB constraint is the arbiter for uniqueness.** Catch `IntegrityError`,
   translate to 409. Never check-then-insert.
3. **Every error is problem+json** via `register_exception_handlers`.
4. **Authorization is asked, never inspected.** `has_perm(principal, Perm.X)`.
   No role-name comparisons at call sites. Gates are module-level singletons —
   an inline `Depends(require(...))` is un-overridable in tests.
5. **Migrations read one explicit `MIGRATION_DATABASE_URL`** and refuse to guess.
6. **No lazy IO after an `await`.** Eager-load it or you get `MissingGreenlet`
   in production and nowhere else.
7. **Background work is dispatched two ways, and both must work.** Broker mode
   (worker + beat) and workerless mode (ADR 010), where the seam drains the
   outbox after committing. Nothing calls `.delay()` directly — if you add a
   call site that does, it will not exist in one of the two modes. Stage an
   outbox event instead.

## The trust boundary

`app/services/reduction.py` is the only consumer of resume/JD prose in the
system. Everything downstream takes a `Selectors` struct of validated enums.

If you are about to:

- add a parameter to `build_grading_payload()` — **stop.** The whitelist is the
  control, and `tests/unit/test_score_invariance.py` asserts the signature.
- pass `question.prompt` to the grader — **stop.** That includes resume-derived
  framing. The grader gets `question.neutral_wording`.
- derive a rubric from anything a user supplied — **stop.** Rubrics come from
  the bank, keyed by `(competency_id, seniority)`.

## Adding a question to the bank

Both P0 domains are fully authored — 52 rubrics, every competency at mid and
senior. Adding a domain means adding rubrics for its competencies; reduction
skips any competency with no authored rubric rather than asking it badly.

1. Add a `QuestionSpec` to `app/content/bank_databases.py` or
   `bank_backend.py`. Both mid and senior, or the governance test fails.
2. Meet the bar: ≥2 core concepts, ≥3 `acceptable_signals` per core concept,
   ≥2 misconceptions overall, `why_it_matters` on every concept, a `signpost`
   on every core concept, and one `strong` + one `weak` golden answer.
3. Write `acceptable_signals` as **things a person actually says** — "it has to
   walk past all those rows first" — never as the terminology. If a concept
   `label` can be answered with one word, the validator rejects it.
4. `docker compose run --rm seed` (idempotent; validates before writing).

## Testing notes

- `tests/unit/` needs no services. `tests/integration/` needs postgres + redis.
- The harness gives each pytest session a private schema, pinned via
  `connect_args` — **not** a `SET` in a `connect` event, which gets rolled back
  when the connection returns to the pool. `test_isolation.py` asserts this.
- The async session in tests is a sync one behind an async facade. It cannot
  catch `MissingGreenlet`. Run `./scripts/smoke.sh`.
- Matrix tests (authz, state machine) use **hand-written expectation tables**.
  Importing the implementation's own map would prove nothing.

## Cost

Cost is a design constraint, not a metric (§8.3). Before adding an LLM call,
check whether the bank can answer instead — planning deliberately makes zero
model calls. Every call must record `UsageCost`.
