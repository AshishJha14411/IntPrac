"""Turning concept verdicts into scores. Pure functions, no IO.

Two properties this module is built to guarantee, both testable:

* **Score invariance (IR-3).** Score is a function of ``(verdicts, weights)``
  and nothing else. There is no parameter here through which a resume, a name,
  or a history could influence a number -- not because we promise not to pass
  one, but because the signature has nowhere to put it.
* **Hints reduce credit on the concepts they touched, never the whole answer**
  (FR-E4e). ``hint_discounted`` is per concept, so a hint on concept 3 cannot
  quietly tax concepts 1 and 2.

Both raw and hint-adjusted scores are always produced. Never one without the
other -- showing only the adjusted score would hide the penalty, and showing
only the raw one would hide the help.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.enums import ConceptWeight, Verdict

#: What each weight class contributes. `core` dominates because conceptual
#: correctness is the highest-weighted axis (FR-E3); `bonus` is upside only.
WEIGHT_POINTS: Mapping[str, float] = {
    ConceptWeight.CORE: 3.0,
    ConceptWeight.SUPPORTING: 1.5,
    ConceptWeight.BONUS: 0.5,
}

#: Credit per verdict. `contradicted` is negative on purpose: a confidently
#: wrong mental model is worse than silence, and scoring it as zero would put
#: "said nothing" and "said something incorrect" on the same footing.
VERDICT_CREDIT: Mapping[str, float] = {
    Verdict.COVERED: 1.0,
    Verdict.PARTIAL: 0.5,
    Verdict.MISSING: 0.0,
    Verdict.CONTRADICTED: -0.5,
}

#: A hint that touched a concept halves its credit -- it does not zero it. The
#: candidate still had to build on the hint, and that work is worth something.
HINT_CREDIT_MULTIPLIER = 0.5

#: Written anchors, so a "3/5" means the same thing across candidates and over
#: time. Bands are (inclusive lower bound on 0-1 score, band, anchor).
BAND_ANCHORS: tuple[tuple[float, int, str], ...] = (
    (0.85, 5, "Explains the mechanism and its trade-offs, and knows when not to apply it."),
    (0.65, 4, "Right mental model with most consequences; some depth still missing."),
    (0.45, 3, "Core idea is present but the mechanism is partly assembled."),
    (0.25, 2, "Fragments of the idea; the underlying model is not yet there."),
    (0.00, 1, "The mechanism is absent or contradicted."),
)


@dataclass(frozen=True, slots=True)
class ScoredConcept:
    concept_id: str
    weight: str
    verdict: str
    hint_discounted: bool = False


@dataclass(frozen=True, slots=True)
class QuestionScore:
    raw: float
    hint_adjusted: float
    band: int
    band_anchor: str
    covered: int
    partial: int
    missing: int
    contradicted: int
    core_total: int
    core_missing: int

    @property
    def all_core_missing(self) -> bool:
        """Drives the derived ``unsubstantiated_claim`` flag (FR-M-A4)."""
        return self.core_total > 0 and self.core_missing == self.core_total


def _normalised(concepts: Sequence[ScoredConcept], *, apply_hints: bool) -> float:
    """Weighted credit as a 0..1 fraction of the achievable total.

    ``bonus`` concepts are excluded from the denominator so failing to reach a
    senior-flavoured extra cannot drag a solid answer down; they can only add.
    """
    earned = 0.0
    possible = 0.0
    for concept in concepts:
        points = WEIGHT_POINTS.get(concept.weight, 1.0)
        credit = VERDICT_CREDIT.get(concept.verdict, 0.0)
        if apply_hints and concept.hint_discounted and credit > 0:
            credit *= HINT_CREDIT_MULTIPLIER
        earned += points * credit
        if concept.weight != ConceptWeight.BONUS:
            possible += points
    if possible <= 0:
        return 0.0
    return max(0.0, min(1.0, earned / possible))


def band_for(score: float) -> tuple[int, str]:
    for threshold, band, anchor in BAND_ANCHORS:
        if score >= threshold:
            return band, anchor
    return 1, BAND_ANCHORS[-1][2]


def score_question(concepts: Sequence[ScoredConcept]) -> QuestionScore:
    raw = _normalised(concepts, apply_hints=False)
    adjusted = _normalised(concepts, apply_hints=True)
    band, anchor = band_for(adjusted)
    core = [concept for concept in concepts if concept.weight == ConceptWeight.CORE]
    return QuestionScore(
        raw=round(raw, 4),
        hint_adjusted=round(adjusted, 4),
        band=band,
        band_anchor=anchor,
        covered=sum(1 for c in concepts if c.verdict == Verdict.COVERED),
        partial=sum(1 for c in concepts if c.verdict == Verdict.PARTIAL),
        missing=sum(1 for c in concepts if c.verdict == Verdict.MISSING),
        contradicted=sum(1 for c in concepts if c.verdict == Verdict.CONTRADICTED),
        core_total=len(core),
        core_missing=sum(1 for c in core if c.verdict in (Verdict.MISSING, Verdict.CONTRADICTED)),
    )


@dataclass(frozen=True, slots=True)
class CompetencyRollup:
    competency_id: str
    band: int
    band_anchor: str
    raw: float
    hint_adjusted: float
    question_count: int


def rollup_competency(
    competency_id: str, question_scores: Sequence[QuestionScore]
) -> CompetencyRollup:
    if not question_scores:
        return CompetencyRollup(competency_id, 1, BAND_ANCHORS[-1][2], 0.0, 0.0, 0)
    raw = sum(score.raw for score in question_scores) / len(question_scores)
    adjusted = sum(score.hint_adjusted for score in question_scores) / len(question_scores)
    band, anchor = band_for(adjusted)
    return CompetencyRollup(
        competency_id=competency_id,
        band=band,
        band_anchor=anchor,
        raw=round(raw, 4),
        hint_adjusted=round(adjusted, 4),
        question_count=len(question_scores),
    )


#: Never a naked percentage (FR-E3) -- the band carries the meaning.
RECOMMENDATION_BANDS: tuple[tuple[float, str], ...] = (
    (0.80, "strong"),
    (0.60, "promising"),
    (0.40, "developing"),
    (0.00, "early"),
)


def recommendation_for(overall: float) -> str:
    for threshold, label in RECOMMENDATION_BANDS:
        if overall >= threshold:
            return label
    return "early"
