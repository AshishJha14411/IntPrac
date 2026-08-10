# 001 — No Kubernetes

**Status:** Accepted · **Date:** 2026-07-28

## Context
The audience is the author and a handful of friends — tens of users, not thousands
(§1.3). Kubernetes is the reflexive answer to "how do I deploy this".

## Decision
Deploy with Docker Compose on a single host. No orchestrator.

## Consequences
The properties Kubernetes would buy — rolling deploys without dropping traffic,
restart-on-failure, health-gated readiness — are the *properties*, not the tool.
Compose provides `restart`, `healthcheck`, and `stop_grace_period`, and the drain
logic that actually protects a live interview (NFR-S3) is in the application
where it belongs, not in an orchestrator's shutdown hook.

Running a control plane for one API container, one worker and one Postgres would
cost more operational surface than the entire product. The concepts are an
afternoon of reading; running it here is cosplay.

**What we gave up:** multi-node scheduling and horizontal autoscaling, neither of
which has a problem to solve at this size. If load ever justifies it, the app is
a stateless container with a pooled database connection — the migration is a
manifest, not a rewrite.
