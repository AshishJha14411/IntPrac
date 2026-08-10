# 003 — No read replicas, no sharding, no CQRS

**Status:** Accepted · **Date:** 2026-07-28

## Context
The read paths (report, progress, history) are heavier than the writes, which is
the usual trigger for replicas or a separate read model.

## Decision
One Postgres. Reads and writes on the same instance, with indexes and query
shape doing the work.

## Consequences
At tens of users the entire dataset fits in memory. A replica would add
replication lag — and lag is a *correctness* problem here: a candidate finishing
an interview and immediately opening their report would sometimes see a session
that doesn't exist yet.

Sharding needs a partition key, and the natural one (user) makes every
cross-user query — bank health, calibration, adverse-impact review — a scatter
gather. Buying that for a table with thousands of rows would be pure cost.

**The one exception worth building:** the progress read model (FR-F4) is
computed with a window function over evaluations rather than recomputed per page
load. That is CQRS-lite in the only place it earns its keep — a precomputed
projection, not a second datastore.

**Revisit when:** the report query stops meeting its latency budget on real
data, measured with `EXPLAIN ANALYZE`, not guessed at.
