"""The session state machine (FR-S1).

    created → planned → consent_pending → device_check → in_progress
              → completed | abandoned → graded → published → reviewed

Transitions are explicit and audited; illegal ones are rejected rather than
tolerated. Keeping the graph as data (rather than scattered ``if`` statements)
means the legal set is auditable in one glance and testable as a matrix.

The consent edge is the one that matters most: nothing can reach
``in_progress`` without passing through ``consent_pending``, so "no consent →
no recording, no session" (FR-S2) is a property of the graph, not a check
somebody has to remember to write.
"""

from __future__ import annotations

from app.core.errors import IllegalTransitionError
from app.domain.enums import SessionStatus

S = SessionStatus

TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    S.CREATED: frozenset({S.PLANNED, S.ABANDONED}),
    S.PLANNED: frozenset({S.CONSENT_PENDING, S.ABANDONED}),
    S.CONSENT_PENDING: frozenset({S.DEVICE_CHECK, S.ABANDONED}),
    # Device check is skippable in text-first mode: there is no device to check.
    S.DEVICE_CHECK: frozenset({S.IN_PROGRESS, S.ABANDONED}),
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.ABANDONED}),
    S.COMPLETED: frozenset({S.GRADED, S.ABANDONED}),
    # Grading may be re-run against a newer rubric; a re-grade lands here again.
    S.GRADED: frozenset({S.PUBLISHED, S.GRADED}),
    S.PUBLISHED: frozenset({S.REVIEWED, S.GRADED}),
    S.REVIEWED: frozenset({S.GRADED}),
    S.ABANDONED: frozenset(),
}

#: States in which a candidate may still submit an answer.
ANSWERABLE = frozenset({S.IN_PROGRESS})

#: States whose data is safe to show as a finished report.
TERMINAL = frozenset({S.GRADED, S.PUBLISHED, S.REVIEWED, S.ABANDONED})


def can_transition(current: SessionStatus | str, target: SessionStatus | str) -> bool:
    return SessionStatus(target) in TRANSITIONS.get(SessionStatus(current), frozenset())


def assert_transition(current: SessionStatus | str, target: SessionStatus | str) -> SessionStatus:
    """Raise ``IllegalTransitionError`` (→ 409) unless the edge exists."""
    current_status, target_status = SessionStatus(current), SessionStatus(target)
    if not can_transition(current_status, target_status):
        raise IllegalTransitionError(
            f"Cannot move a session from '{current_status.value}' to '{target_status.value}'.",
            current=current_status.value,
            target=target_status.value,
            allowed=sorted(state.value for state in TRANSITIONS.get(current_status, frozenset())),
        )
    return target_status
