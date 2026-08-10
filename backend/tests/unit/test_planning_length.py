"""How long a session is chosen to be, and how many questions that buys.

Duration used to be spent by packing each question's ``expected_minutes``,
which read as principled and behaved badly: the estimates sit at 5-7 minutes,
so a 10-minute session got two questions and a 45-minute one got seven. The
candidate's choice of length barely moved anything. These tests pin the
replacement curve, and the properties that make it safe to change the anchors.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.planning import QUESTIONS_BY_MINUTES, target_question_count


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(10, 6), (20, 10), (30, 14), (45, 20)],
)
def test_the_published_durations_get_the_counts_we_promised(
    minutes: int, expected: int
) -> None:
    """These four are the options the UI actually offers."""
    assert target_question_count(minutes) == expected


def test_longer_is_never_shorter() -> None:
    """Monotonicity is the property a user would notice breaking.

    Picking a longer session and getting fewer questions would read as a bug
    no matter how defensible the arithmetic was.
    """
    counts = [target_question_count(m) for m in range(1, 121)]
    assert counts == sorted(counts)


def test_between_the_anchors_lands_between_them() -> None:
    """A duration nobody anchored still has to behave sensibly."""
    assert 6 <= target_question_count(15) <= 10
    assert 10 <= target_question_count(25) <= 14


def test_a_very_short_session_still_asks_something() -> None:
    """Never zero: a one-minute session is odd, an empty one is broken."""
    assert target_question_count(1) >= 1
    assert target_question_count(0) >= 1


def test_beyond_the_last_anchor_it_holds_rather_than_extrapolating() -> None:
    """Two hours must not linearly imply fifty questions.

    Extrapolation past the last anchor is how a plausible curve produces an
    interview nobody would sit through.
    """
    ceiling = QUESTIONS_BY_MINUTES[-1][1]
    assert target_question_count(90) == ceiling
    assert target_question_count(600) == ceiling


def test_the_competency_cap_can_supply_the_longest_session() -> None:
    """The two limits have to agree, or the longest session silently truncates.

    Reduction keeps at most ``MAX_COMPETENCIES``, and a question needs a
    competency, so a cap below the top of the curve is an invisible ceiling on
    the 45-minute option.
    """
    from app.services.reduction import MAX_COMPETENCIES

    assert QUESTIONS_BY_MINUTES[-1][1] <= MAX_COMPETENCIES


def test_the_access_token_outlives_the_longest_interview() -> None:
    """The bug this encodes: candidates were logged out mid-answer.

    A 15-minute access token against a 45-minute interview meant the session
    expired three times over, and nothing renewed it. The client refreshes on
    a 401 now, but the token should not expire during a normal sitting in the
    first place.
    """
    settings = Settings()
    longest_minutes = QUESTIONS_BY_MINUTES[-1][0]
    assert settings.access_token_ttl_seconds > longest_minutes * 60
    # And the refresh token must comfortably outlive the access token, or
    # renewal has nothing to renew against.
    assert settings.refresh_token_ttl_seconds > settings.access_token_ttl_seconds
