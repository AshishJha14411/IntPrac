"""Session state machine (FR-S1) -- an independently written transition grid.

Same discipline as the authz matrix: the legal edges are written out by hand
here rather than imported, so a change to the graph has to be an intentional
change to this table too.
"""

from __future__ import annotations

import pytest

from app.core.errors import IllegalTransitionError
from app.domain.enums import SessionStatus as S
from app.domain.state_machine import ANSWERABLE, assert_transition, can_transition

LEGAL: set[tuple[S, S]] = {
    (S.CREATED, S.PLANNED),
    (S.CREATED, S.ABANDONED),
    (S.PLANNED, S.CONSENT_PENDING),
    (S.PLANNED, S.ABANDONED),
    (S.CONSENT_PENDING, S.DEVICE_CHECK),
    (S.CONSENT_PENDING, S.ABANDONED),
    (S.DEVICE_CHECK, S.IN_PROGRESS),
    (S.DEVICE_CHECK, S.ABANDONED),
    (S.IN_PROGRESS, S.COMPLETED),
    (S.IN_PROGRESS, S.ABANDONED),
    (S.COMPLETED, S.GRADED),
    (S.COMPLETED, S.ABANDONED),
    (S.GRADED, S.PUBLISHED),
    (S.GRADED, S.GRADED),
    (S.PUBLISHED, S.REVIEWED),
    (S.PUBLISHED, S.GRADED),
    (S.REVIEWED, S.GRADED),
}


@pytest.mark.parametrize("current", list(S))
@pytest.mark.parametrize("target", list(S))
def test_transition_grid(current: S, target: S) -> None:
    assert can_transition(current, target) is ((current, target) in LEGAL)


def test_illegal_transition_raises_a_conflict() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        assert_transition(S.CREATED, S.IN_PROGRESS)
    assert excinfo.value.status == 409
    # The error names what *is* allowed, so the caller can act on it.
    assert "planned" in excinfo.value.extra["allowed"]


def test_consent_is_unskippable() -> None:
    """FR-S2: no consent -> no recording, no session.

    There is no edge from `planned` straight to `in_progress`, so the gate is a
    property of the graph rather than a check somebody has to remember.
    """
    assert not can_transition(S.PLANNED, S.IN_PROGRESS)
    assert not can_transition(S.PLANNED, S.DEVICE_CHECK)
    assert not can_transition(S.CREATED, S.IN_PROGRESS)


def test_abandoned_is_terminal() -> None:
    for target in S:
        assert not can_transition(S.ABANDONED, target)


def test_only_in_progress_accepts_answers() -> None:
    assert {S.IN_PROGRESS} == ANSWERABLE


def test_regrade_is_possible_from_every_published_state() -> None:
    """§9.3: a discovered rubric flaw must be correctable across affected candidates."""
    assert can_transition(S.PUBLISHED, S.GRADED)
    assert can_transition(S.REVIEWED, S.GRADED)
    assert can_transition(S.GRADED, S.GRADED)
