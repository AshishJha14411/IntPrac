# 008 — The scoring isolation boundary

**Status:** Accepted · **Date:** 2026-07-28

## Context

A resume is attacker-controlled text. The obvious defence — sanitise the prose,
detect instruction-like content, tell the model to ignore embedded commands —
is a filter, and filters are never complete. Anything built on "we catch the
bad inputs" fails on the first input nobody thought of.

There is a second, larger problem that has nothing to do with attackers.
If resume or JD prose can influence a rubric, then two candidates giving the
same answer can receive different scores because one of them has a more
impressive-sounding background. That is not a security bug; it is the product
being wrong.

## Decision

Resume and JD prose are confined to a single step — **reduction** — and
discarded there. Reduction emits a `Selectors` struct of validated,
closed-taxonomy enums, and every component downstream takes that struct.

Three properties make this structural rather than aspirational:

1. **`Selectors` has no free-text field.** There is nowhere for prose to sit.
2. **`build_grading_payload()` takes exactly three arguments** — bank wording,
   rubric concepts, transcript — and no `**kwargs`. There is no parameter
   through which a resume could reach the grader, so adding one requires
   changing a signature that a test asserts.
3. **Rubrics come from the bank**, keyed by `(competency_id, seniority)`, and
   are *copied onto the question at plan time*. The standard is identical for
   every candidate at that level and cannot be edited retroactively.

The reducer's output is validated against the taxonomy; anything not in it is
dropped and counted, never trusted.

## Consequences

**What we get.** The maximum achievable impact of a hostile document is *the
wrong topics were selected* — a quality bug, not a scoring compromise. Score
invariance (IR-3) follows: identical answers earn identical scores whatever the
resume said. Comparability (FR-P4) follows too, because the standard is
shared. And every score becomes explainable, because it is a function of quoted
evidence against a rubric a human wrote.

**What it costs.** Questions cannot be tailored beyond cosmetic framing, so a
curated bank becomes mandatory — which is real, ongoing authoring work, and it
is the reason the bank ships with 24 rubrics rather than a generated infinity.
A competency with no authored rubric simply cannot be interviewed on.

**What we gave up.** The tempting version of this product generates a bespoke
question *and* its grading standard from the candidate's own resume. That
version is more impressive in a demo and indefensible in a hiring decision: the
bar moves with the document, and nobody can say what a "4/5" meant.

## Enforcement

Not a convention — a test. `tests/unit/test_score_invariance.py` asserts the
payload's exact key set, asserts the function signature has no escape hatch,
and grades the same transcript against flattering, weak, and injection-laden
resumes. A failure there is a release blocker, because it means prose leaked
into scoring.
