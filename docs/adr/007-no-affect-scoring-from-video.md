# 007 — No emotion, affect, or confidence scoring

**Status:** Accepted (permanent) · **Date:** 2026-07-28

## Context
Video is captured for human review. Once it exists, inferring "confidence",
"enthusiasm" or "cultural fit" from face or voice is a small technical step and
a frequently requested feature.

## Decision
Never. Video and audio are evidence for a human, never input to a model that
scores. The grader consumes the transcript only, and the consent screen states
this in the negative — accent, fluency, grammar, speaking speed, confidence, and
anything inferred from face or voice are explicitly not assessed.

## Consequences
Three independent reasons, any one sufficient:

1. **It doesn't work.** Affect recognition has weak construct validity; the
   mapping from facial movement to internal state does not survive contact with
   individual and cultural variation.
2. **It is discriminatory in a measurable way.** Error rates vary by ethnicity,
   age, and disability — including conditions that directly affect facial
   expression and speech. A "confidence" score is a proxy for neurotype and
   first language.
3. **It is restricted or banned** in several jurisdictions for exactly this
   purpose.

**What we gave up:** nothing we wanted. The signal a candidate actually needs is
"which idea did I not reach", and that is in the transcript.

This one is not a scale-dependent trade-off to revisit later. It is a
requirement (§2.2) and this ADR exists so the answer is written down before the
question gets asked.
