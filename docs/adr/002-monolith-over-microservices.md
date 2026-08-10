# 002 — A modular monolith, not microservices

**Status:** Accepted · **Date:** 2026-07-28

## Context
The system has clear seams — intake, reduction, planning, the interview loop,
grading, reporting. Those seams are exactly where someone would draw service
boundaries.

## Decision
One deployable, with the seams enforced in code: `services/` modules that depend
on typed structs rather than each other's internals, and a trust boundary
(`Selectors`) that is stricter than most network boundaries would be.

## Consequences
The boundary that actually matters here is **what data may cross it**, not what
process it runs in. Splitting reduction into its own service would not make
IR-3 any more true — the guarantee comes from the function signature and the
schema, and those hold identically in-process.

Against that, splitting would add: a network hop inside the interview turn loop
(which has a 3-second p95 budget), distributed transactions where there is
currently one, and a deployment story per service.

**What we gave up:** independent scaling and independent deploys. At tens of
users neither has a problem to solve, and the grading path — the one component
with genuinely different resource needs — is already separated as a worker with
its own queue.

Knowing *why* the monolith is correct here is the point; reaching for services
by reflex is the failure mode.
