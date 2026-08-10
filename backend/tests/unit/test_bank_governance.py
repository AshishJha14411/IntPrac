"""The bank's own quality gate (FR-B2b/c/e).

The content library is the product's standard. A mis-authored rubric doesn't
fail loudly at runtime -- it quietly grades someone against the wrong bar -- so
the bar is enforced here and in the seed script, before anything ships.
"""

from __future__ import annotations

import pytest

from app.content.bank_backend import QUESTIONS as BACKEND_QUESTIONS
from app.content.bank_databases import QUESTIONS as DATABASE_QUESTIONS
from app.content.taxonomy import TAXONOMY, TAXONOMY_IDS
from app.content.types import (
    BankValidationError,
    ConceptSpec,
    QuestionSpec,
    validate_bank,
    validate_question,
)
from app.domain.enums import ConceptWeight, Seniority

ALL_QUESTIONS = (*DATABASE_QUESTIONS, *BACKEND_QUESTIONS)


def test_the_shipped_bank_meets_the_authoring_bar() -> None:
    validate_bank(list(ALL_QUESTIONS))


def test_every_question_targets_a_taxonomy_competency() -> None:
    """IR-4: a question outside the closed vocabulary can never be selected."""
    for spec in ALL_QUESTIONS:
        assert spec.competency_id in TAXONOMY_IDS, spec.competency_id


def test_taxonomy_ids_are_unique() -> None:
    ids = [spec.competency_id for spec in TAXONOMY]
    assert len(ids) == len(set(ids))


def test_no_duplicate_question_keys() -> None:
    keys = [(spec.competency_id, spec.seniority, spec.rubric_version) for spec in ALL_QUESTIONS]
    assert len(keys) == len(set(keys))


def test_terminology_screen_rejects_a_bare_term_label() -> None:
    """FR-B2c: if a label can be 'answered' with a term, it is mis-authored."""
    bad = QuestionSpec(
        competency_id="indexing-strategy",
        seniority=Seniority.MID,
        neutral_wording="Q?",
        concepts=(
            ConceptSpec(
                "c1",
                "Keyset pagination",  # a term, not an idea
                ConceptWeight.CORE,
                "why",
                ("a", "b", "c"),
                (),
                "signpost",
            ),
        ),
    )
    problems = validate_question(bad)
    assert any("satisfiable by naming a term" in problem for problem in problems)


def test_core_concepts_need_enough_signals() -> None:
    """Fewer than three paraphrases means the grader has too little to match on."""
    bad = QuestionSpec(
        competency_id="indexing-strategy",
        seniority=Seniority.MID,
        neutral_wording="Q?",
        concepts=(
            ConceptSpec(
                "c1",
                "An index is a separate ordered structure the database can jump into",
                ConceptWeight.CORE,
                "why",
                ("only one signal",),
                (),
                "signpost",
            ),
        ),
    )
    assert any("acceptable_signals" in problem for problem in validate_question(bad))


def test_a_rubric_without_goldens_cannot_ship() -> None:
    """FR-B2e: the drift gate needs fixtures, or it is decoration."""
    spec = QuestionSpec(
        competency_id="indexing-strategy",
        seniority=Seniority.MID,
        neutral_wording="Q?",
        concepts=(
            ConceptSpec(
                "c1",
                "An index is a separate ordered structure the database can jump into",
                ConceptWeight.CORE,
                "why",
                ("a b c", "d e f", "g h i"),
                ("wrong idea one", "wrong idea two"),
                "signpost",
            ),
            ConceptSpec(
                "c2",
                "Column order decides which queries the index can serve",
                ConceptWeight.CORE,
                "why",
                ("a b c", "d e f", "g h i"),
                (),
                "signpost",
            ),
        ),
    )
    assert any("golden answer" in problem for problem in validate_question(spec))


def test_validate_bank_raises_with_every_problem_listed() -> None:
    """One run should tell an author everything to fix, not just the first thing."""
    bad = QuestionSpec(
        competency_id="indexing-strategy",
        seniority=Seniority.MID,
        neutral_wording="Q?",
        concepts=(ConceptSpec("c1", "Indexes", ConceptWeight.CORE, "", (), (), None),),
    )
    with pytest.raises(BankValidationError) as excinfo:
        validate_bank([bad])
    message = str(excinfo.value)
    assert "why_it_matters" in message
    assert "core concepts" in message


def test_every_core_concept_has_a_signpost_that_names_no_signal() -> None:
    """FR-E4b: the L2 hint must not hand over the words the grader looks for.

    A signpost that repeats an acceptable signal verbatim would score the hint
    rather than the candidate.
    """
    for spec in ALL_QUESTIONS:
        for concept in spec.concepts:
            if concept.weight is not ConceptWeight.CORE:
                continue
            assert concept.signpost, f"{spec.competency_id}/{concept.concept_id}"
            signpost = concept.signpost.lower()
            for signal in concept.acceptable_signals:
                assert signal.lower() not in signpost, (
                    f"{spec.competency_id}/{concept.concept_id}: the signpost quotes an "
                    f"acceptable signal ('{signal}') -- that gives away the answer"
                )


def test_golden_expectations_reference_real_concepts() -> None:
    for spec in ALL_QUESTIONS:
        valid = {concept.concept_id for concept in spec.concepts}
        for golden in spec.goldens:
            unknown = set(golden.expected) - valid
            assert not unknown, f"{spec.competency_id}/{spec.seniority}: {unknown}"


def test_bank_covers_both_seniorities_for_every_competency_it_touches() -> None:
    """Appendix C.2: the same competency at a different level is a different rubric.

    Shipping only one level means a session at the other level silently drops
    the topic, which looks like a planning bug rather than a content gap.
    """
    by_competency: dict[str, set[str]] = {}
    for spec in ALL_QUESTIONS:
        by_competency.setdefault(spec.competency_id, set()).add(spec.seniority.value)
    incomplete = {
        competency: levels
        for competency, levels in by_competency.items()
        if levels != {"mid", "senior"}
    }
    assert not incomplete, f"competencies missing a level: {incomplete}"


def test_the_system_design_domain_is_authored_at_both_levels() -> None:
    """A competency authored at one level only is invisible at the other.

    Reduction may select it, `_load_bank` finds no rubric for that seniority,
    and the question is silently dropped -- the interview is just shorter, with
    nothing anywhere saying why.
    """
    from app.content.bank_system_design import QUESTIONS as SYSTEM_DESIGN

    by_competency: dict[str, set[str]] = {}
    for spec in SYSTEM_DESIGN:
        by_competency.setdefault(spec.competency_id, set()).add(spec.seniority.value)

    assert by_competency, "the system-design bank is empty"
    incomplete = {cid: levels for cid, levels in by_competency.items() if len(levels) < 2}
    assert not incomplete, f"authored at one seniority only: {incomplete}"


def test_the_bank_can_fill_the_longest_session() -> None:
    """Duration is only a promise if the bank has the material to keep it.

    The 45-minute option asks for twenty questions. A question needs a
    competency with an authored rubric at that seniority, so if the bank holds
    fewer than that, the longest session is capped by content and no amount of
    planning logic changes it.
    """
    from app.content.seed import ALL_QUESTIONS
    from app.services.planning import QUESTIONS_BY_MINUTES

    wanted = QUESTIONS_BY_MINUTES[-1][1]
    for level in ("mid", "senior"):
        available = {
            spec.competency_id for spec in ALL_QUESTIONS if spec.seniority.value == level
        }
        assert len(available) >= wanted, (
            f"{level}: {len(available)} competencies authored, "
            f"but a {QUESTIONS_BY_MINUTES[-1][0]}-minute session wants {wanted}"
        )


def test_no_signal_is_just_the_jargon_it_stands_for() -> None:
    """FR-B2c, applied to the signals rather than the labels.

    A rubric whose acceptable signal *is* the term rewards saying the word,
    which is the one thing this product refuses to score. System-design has the
    densest jargon of the three domains, so this matters most there.
    """
    from app.content.seed import ALL_QUESTIONS

    banned = {
        "backpressure",
        "idempotent",
        "idempotency",
        "quorum",
        "cap theorem",
        "circuit breaker",
        "sharding",
        "jitter",
        "eventual consistency",
    }
    offenders: list[str] = []
    for spec in ALL_QUESTIONS:
        for concept in spec.concepts:
            for signal in concept.acceptable_signals:
                normalised = signal.strip().lower().rstrip(".")
                if normalised in banned:
                    offenders.append(f"{spec.competency_id}/{concept.concept_id}: '{signal}'")
    assert not offenders, "signals that only reward the vocabulary:\n  " + "\n  ".join(offenders)
