# 010 — Optional workerless dispatch: the request drains its own outbox

**Status:** Accepted · **Date:** 2026-07-31

## Context

Background work here is dispatched through a transactional outbox (ADR 005): a
write stages an event row in the same transaction as the domain change, and a
relay on Celery **beat** claims pending rows every five seconds and turns them
into `.delay()` calls that a Celery **worker** executes.

That is two processes with no HTTP surface. A Celery worker is a *polling*
consumer — it sits in a `BRPOP` loop against the broker — and beat is a timer.
Neither is driven by requests, so on a scale-to-zero host (Cloud Run and
equivalents allocate CPU in response to requests) both must be pinned:

```
--min-instances=1 --max-instances=1 --no-cpu-throttling
```

Two CPUs billed 24/7 for a system that is idle most of the day, plus the broker
polling itself: kombu issues roughly one command per second forever, which on a
metered Redis is tens of thousands of commands a day produced by nothing
happening. Every other component in the stack scales to zero; these would be
the entire bill.

§8.3 says cost is a design constraint, not a metric. A deployment that cannot
be afforded is not a deployment.

The same problem was met and solved in the v1 project (its ADR 001). This is
the same decision, adapted — and the adaptation is the substance of this one.

## Decision

Support two dispatch modes behind one flag, `CELERY_TASK_ALWAYS_EAGER`.

**Broker mode (default, and what local `docker compose up` runs).** Unchanged:
worker, beat, queues, bulkheads, retries with backoff.

**Workerless mode.** `task_always_eager=True` makes `.delay()` run the task
inline in the calling process, `task_eager_propagates=False` keeps a failing
task from raising into whatever called it, and there is no worker, no beat, and
no broker traffic at all.

### Why the flag alone is not the decision

In v1 that flag *was* the whole change, because every call site there calls
`.delay()` directly. Here nothing does. Writes stage an outbox row, and the
only thing that turns rows into `.delay()` calls is the relay — which runs on
beat, the second process we are trying not to pay for. Setting the flag and
deleting both processes would produce an API that returns 200 for every write
and never grades anything, with no error anywhere. That is a worse failure than
the cost.

So workerless mode adds the missing half: **the unit-of-work seam drains the
outbox itself, after its own transaction commits** (`app/services/dispatch.py`,
called from `app/db/session.py`). Three properties fall out of where it sits:

- *After the commit*, so the relay can only ever see events that are real —
  the same ordering guarantee the outbox exists for.
- *Inside the request, not after the response.* `BackgroundTasks` and
  post-response hooks would keep the request fast and would also quietly not
  work: CPU is allocated in response to a request, so work scheduled after the
  response is throttled to near-nothing and dies with the instance. This is why
  the drain is awaited rather than fired and forgotten.
- *On a thread*, because the relay is sync by design (Appendix D.4) and running
  it on the event loop would block every other request on the instance.

### Two consequences of "the task already ran"

**The relay must ask whether the inline run worked.** With
`task_eager_propagates=False`, a failure comes back as a *result*, not an
exception. A relay watching only for exceptions would mark the row published
and drop the work. It checks `result.successful()` — not `not failed()`,
because a task that called `self.retry()` lands in `RETRY`, and with no broker
nothing will ever pick that up. On anything short of success the row stays
`pending` and the existing `attempts` / `last_error` / `MAX_ATTEMPTS` columns
carry the retry. **The outbox, which was built as a delivery guarantee, becomes
the retry mechanism** — the one thing eager mode takes away.

**A request must not be held open by a queue.** The drain stops at a wall-clock
budget (`INLINE_DRAIN_BUDGET_SECONDS`, default 10s) checked *before* starting
each event, so a request can absorb one over-budget task but never a backlog of
them. What it skips is still `pending`, which is where it already was.

### What replaces beat's scheduled work

`app/entrypoints/jobs.py` runs one job and exits, so retention is driven by an
external scheduler — Cloud Run Jobs, a GitHub Actions `schedule:`, cron —
none of which idles. Dropping beat without this would silently turn NFR-P's
retention promise back into a policy document, on a system holding video, voice
and resumes.

## Consequences

**What it costs.**

- *Latency becomes user-visible, and here that means seconds, not milliseconds.*
  v1's inline tasks were a local profanity scan; ours is an LLM grading call.
  The request that commits an answer may absorb the grading of a previous one.
  Grading was deliberately off the critical path (§8.1) and in this mode it is
  partly back on it. The budget bounds it to one task per request; it does not
  make it free.
- *No automatic retry with backoff.* Retries happen when a later request
  drains, so they are driven by traffic rather than by a timer. A failing event
  on an idle system waits for the next visitor.
- *An idle system does not drain.* If a candidate closes the tab after their
  last answer, that answer stays ungraded until some request arrives — theirs
  when they return, or `jobs.py drain` from a scheduler. Self-healing, but
  latent, and worth knowing before reading the outbox table in anger.
- *The relay holds its transaction open while dispatching*, so a drain that
  runs a 20s grading call is a 20s transaction holding row locks. Bounded by
  the budget, and fine at this scale; it would not be at a larger one.
- *No queue bulkheads in this mode.* NFR-S5's isolation between grading and
  media is a property of having queues, and there are none.

**What we gave up.** Genuine asynchrony. Everything above is a restatement of
that one fact.

**What the correct answer would be at scale.** Push delivery, not pull: replace
the polling broker with **Cloud Tasks** (or Pub/Sub push) targeting an
authenticated HTTP endpoint on the API service. The outbox relay enqueues to
Cloud Tasks instead of Celery; Cloud Tasks POSTs; the service cold-starts 0→1,
works, and scales back down. That keeps scale-to-zero *and* asynchrony *and*
managed retries with backoff, is strictly better than both the always-on worker
and this, and at 1M free operations/month would also be free. It is deferred
because it re-architects the dispatch path, where this is a flag plus one hook.

**Revisit when:** grading latency becomes a complaint rather than a note, a
paying user exists, or the outbox shows events routinely surviving more than
one drain.

## How you know which mode is running

`GET /api/v1/health/ready` reports `"dispatch": "inline" | "worker"`.

This is not decoration. Whether a worker exists is deployment state that no
file in the repo can see, and its absence fails silently. In v1 the flag lived
only in a cloud console, so "are background tasks actually running in
production?" could not be answered without opening it — while the visible
symptom would have been stories that never publish. One field turns that into a
`curl`.

## Alternatives considered

| Option | Cost | Why not |
|---|---|---|
| Keep worker + beat always on | ~2 pinned CPUs/mo + broker polling | The problem being solved. |
| `min-instances=0` on the worker | $0 | **Broken, not cheap** — nothing wakes a polling consumer, so the queue never drains. |
| Eager mode alone, as in v1 | $0 | Silently drops every event: nothing calls `.delay()` here, beat does. This ADR exists because of it. |
| `BackgroundTasks` / post-response hooks | $0 | Post-response work is CPU-throttled on a scale-to-zero host and dies without a trace. |
| Scheduled job draining the queue every N minutes | ~$0 | Works, and `jobs.py drain` is exactly this — but as a safety net. As the primary path it adds N minutes to every grade for more moving parts than the seam hook. |
| **Cloud Tasks push → HTTP endpoint** | ~$0 | **The right answer**, deferred as a re-architecture rather than rejected. See above. |
