"""Rating a resume by what could be extracted from it.

The rating exists because planning now tops up a thin plan, so a sparse resume
no longer produces a short interview -- it produces a full one about topics the
candidate never claimed. Useful, but it hides the signal. This gives the signal
back to the person who can act on it.

These tests are mostly about the advice being *coherent*: contradictory
feedback is worse than none, because it teaches people to stop reading it.
"""

from __future__ import annotations

from app.domain.enums import ProfileItemKind
from app.services.resume_quality import SPARSE_COMPETENCIES, THIN_ITEMS, assess

ROLE = ProfileItemKind.ROLE.value
SKILL = ProfileItemKind.SKILL.value
PROJECT = ProfileItemKind.PROJECT.value


def test_a_rich_resume_is_not_told_to_fix_anything() -> None:
    quality = assess(
        competency_ids=[f"topic-{n}" for n in range(12)],
        item_kinds=[ROLE] * 6 + [PROJECT] * 4 + [SKILL] * 5,
        total_chars=6000,
    )
    assert quality.rating == "strong"
    assert quality.competencies_found == 12
    # It still says something -- silence reads as a failed check.
    assert quality.suggestions


def test_a_strong_resume_is_never_told_its_text_is_too_short() -> None:
    """The contradiction this encodes actually shipped.

    A dense one-page resume rated `strong` and was simultaneously told the text
    was very short, because the length rule fired on its own. Advice that
    argues with itself is advice people stop reading, so the broken-extraction
    hint now needs *both* signals.
    """
    quality = assess(
        competency_ids=[f"topic-{n}" for n in range(20)],
        item_kinds=[ROLE] * 10 + [SKILL] * 6,
        total_chars=900,  # short, but plainly extracted fine
    )
    assert quality.rating == "strong"
    assert not any("came out of this file" in s for s in quality.suggestions)


def test_a_scan_that_did_not_extract_is_told_so() -> None:
    """Both signals together: almost no text and almost no items."""
    quality = assess(competency_ids=[], item_kinds=[], total_chars=120)
    assert quality.rating == "sparse"
    assert any("machine-readable" in s for s in quality.suggestions)


def test_a_sparse_resume_is_told_what_would_change_the_outcome() -> None:
    quality = assess(
        competency_ids=["indexing-strategy", "rest-api-design"],
        item_kinds=[SKILL] * 4,
        total_chars=1500,
    )
    assert quality.rating == "sparse"
    # Names the actual lever: topics, not tools.
    assert any("technical topic" in s for s in quality.suggestions)
    assert any("roles or projects" in s.lower() for s in quality.suggestions)


def test_the_thresholds_line_up_with_what_a_session_asks_for() -> None:
    """A rating is only meaningful next to the demand it is rated against.

    A 20-minute session plans 10 questions, so a resume yielding fewer than a
    handful of competencies genuinely cannot carry one on its own -- which is
    what `sparse` is claiming.
    """
    from app.services.planning import target_question_count

    assert target_question_count(20) > SPARSE_COMPETENCIES
    assert THIN_ITEMS > SPARSE_COMPETENCIES


def test_the_rating_is_ordered() -> None:
    """More material must never rate worse."""
    poor = assess(competency_ids=["a"], item_kinds=[SKILL], total_chars=300)
    mid = assess(competency_ids=["a", "b", "c"], item_kinds=[ROLE] * 4, total_chars=2000)
    rich = assess(
        competency_ids=[f"t{n}" for n in range(9)],
        item_kinds=[ROLE] * 9,
        total_chars=5000,
    )
    order = {"sparse": 0, "workable": 1, "strong": 2}
    assert order[poor.rating] < order[mid.rating] < order[rich.rating]
