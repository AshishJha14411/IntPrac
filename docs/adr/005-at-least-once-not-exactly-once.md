# 005 — At-least-once delivery with idempotent consumers, not exactly-once

**Status:** Accepted · **Date:** 2026-07-28

## Context

Two writes in this system dispatch background work: an answer needs grading, a
document needs parsing. Under a commit-at-the-seam unit of work the service
returns *before* the transaction commits, which creates a genuine ordering
problem:

- Enqueue inside the service → the worker can pick the job up before the row is
  visible, and looks for something that isn't there.
- Enqueue after the commit → a crash in the gap between them loses the job
  silently, with no row anywhere recording that it should have happened.

The tempting fix is a queue that promises exactly-once delivery.

## Decision

Use a **transactional outbox** with **at-least-once delivery and idempotent
consumers**.

The event row is written in the same transaction as the domain change, so
either both exist or neither does — the ordering problem disappears rather than
being narrowed. A relay claims pending rows with `FOR UPDATE SKIP LOCKED` and
dispatches them; multiple relays can run without double-sending, and a
dispatcher crash after sending simply redelivers.

Duplicate delivery is then made harmless where it lands:

- Grading is unique per `(answer_id, rubric_version, model_version,
  prompt_version)`, so a redelivery finds the existing evaluation.
- Parsing checks its own terminal state before doing work.
- Answer submission is keyed by a client-supplied idempotency key backed by a
  unique constraint.

## Consequences

**What we get.** No lost jobs across a crash, no worker racing an invisible
row, and no coupling between "the write succeeded" and "the queue was up". A
dead event stays in the table where a human can look at it, rather than
vanishing.

**What it costs.** A relay poll (5s) sits between commit and dispatch, so
grading starts a moment later than a direct enqueue would. Since grading is
deliberately off the critical path (§8.1), that latency is invisible to the
candidate.

**What we gave up.** Exactly-once delivery, which we never had. A broker can
deliver a message once, but it cannot make *your consumer's side effects*
happen exactly once across a crash between "work done" and "ack sent" — that
requires the effect and the acknowledgement to share a transaction, which they
don't. Systems that claim exactly-once are doing at-least-once plus
deduplication, and it is better to name that and put the deduplication where
you can see it.
