"""Scoring properties (§6.3, FR-E4e).

Property-based where the property is genuinely universal, example-based where
a specific behaviour is the requirement.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import ConceptWeight, Verdict
from app.services.scoring import (
    QuestionScore,
    ScoredConcept,
    band_for,
    recommendation_for,
    rollup_competency,
    score_question,
)

weights = st.sampled_from([w.value for w in ConceptWeight])
verdicts = st.sampled_from([v.value for v in Verdict])
concepts = st.lists(
    st.builds(
        ScoredConcept,
        concept_id=st.text(min_size=1, max_size=12),
        weight=weights,
        verdict=verdicts,
        hint_discounted=st.booleans(),
    ),
    min_size=1,
    max_size=8,
)


@given(concepts)
def test_scores_stay_in_range(items: list[ScoredConcept]) -> None:
    score = score_question(items)
    assert 0.0 <= score.raw <= 1.0
    assert 0.0 <= score.hint_adjusted <= 1.0
    assert 1 <= score.band <= 5


@given(concepts)
def test_hints_never_increase_the_score(items: list[ScoredConcept]) -> None:
    """FR-E4e: a hint reduces credit. It must never be worth taking for points."""
    score = score_question(items)
    assert score.hint_adjusted <= score.raw + 1e-9


@given(concepts)
def test_scoring_is_deterministic(items: list[ScoredConcept]) -> None:
    """IR-3's foundation: same input, same output, every time."""
    assert score_question(items) == score_question(items)


def test_hint_only_discounts_the_concept_it_touched() -> None:
    """A hint on concept B must not tax concept A."""
    untouched = [
        ScoredConcept("a", ConceptWeight.CORE, Verdict.COVERED),
        ScoredConcept("b", ConceptWeight.CORE, Verdict.COVERED),
    ]
    touched_b = [
        ScoredConcept("a", ConceptWeight.CORE, Verdict.COVERED),
        ScoredConcept("b", ConceptWeight.CORE, Verdict.COVERED, hint_discounted=True),
    ]
    full = score_question(untouched)
    partial = score_question(touched_b)

    assert full.hint_adjusted == full.raw  # no hints, no discount
    assert partial.raw == full.raw  # the raw score is unaffected by hints
    # Exactly one of two equally-weighted concepts halved -> 75% remains.
    assert partial.hint_adjusted == 0.75


def test_terminology_carries_zero_weight() -> None:
    """FR-E2c: there is no input to `score_question` for terminology at all."""
    import inspect

    signature = inspect.signature(score_question)
    assert list(signature.parameters) == ["concepts"]
    assert set(ScoredConcept.__slots__) == {
        "concept_id",
        "weight",
        "verdict",
        "hint_discounted",
    }


def test_contradicted_scores_below_missing() -> None:
    """A confidently wrong mental model is worse than silence (FR-E2b)."""
    missing = score_question([ScoredConcept("a", ConceptWeight.CORE, Verdict.MISSING)])
    contradicted = score_question(
        [ScoredConcept("a", ConceptWeight.CORE, Verdict.CONTRADICTED)]
    )
    assert contradicted.raw <= missing.raw


def test_bonus_concepts_only_add() -> None:
    """Failing to reach a bonus concept must not drag a solid answer down."""
    without = score_question([ScoredConcept("a", ConceptWeight.CORE, Verdict.COVERED)])
    with_missed_bonus = score_question(
        [
            ScoredConcept("a", ConceptWeight.CORE, Verdict.COVERED),
            ScoredConcept("b", ConceptWeight.BONUS, Verdict.MISSING),
        ]
    )
    assert with_missed_bonus.raw == without.raw


def test_all_core_missing_flag() -> None:
    """Feeds the derived `unsubstantiated_claim` fact (FR-M-A4)."""
    score = score_question(
        [
            ScoredConcept("a", ConceptWeight.CORE, Verdict.MISSING),
            ScoredConcept("b", ConceptWeight.CORE, Verdict.CONTRADICTED),
            ScoredConcept("c", ConceptWeight.SUPPORTING, Verdict.COVERED),
        ]
    )
    assert score.all_core_missing is True


def test_bands_have_written_anchors() -> None:
    """A 3/5 has to mean the same thing to everyone who reads it (FR-E3)."""
    for value in (0.0, 0.3, 0.5, 0.7, 0.95):
        band, anchor = band_for(value)
        assert 1 <= band <= 5
        assert anchor and len(anchor) > 20


def test_recommendation_is_a_band_not_a_percentage() -> None:
    assert recommendation_for(0.95) == "strong"
    assert recommendation_for(0.1) == "early"
    assert isinstance(recommendation_for(0.5), str)


def test_rollup_of_no_questions_is_the_lowest_band() -> None:
    rollup = rollup_competency("x", [])
    assert rollup.band == 1
    assert rollup.question_count == 0


def test_rollup_averages_question_scores() -> None:
    scores = [
        QuestionScore(1.0, 1.0, 5, "a", 1, 0, 0, 0, 1, 0),
        QuestionScore(0.0, 0.0, 1, "b", 0, 0, 1, 0, 1, 1),
    ]
    rollup = rollup_competency("x", scores)
    assert rollup.raw == 0.5
