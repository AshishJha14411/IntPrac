"""Grading tasks.

Retried with backoff and jitter; idempotent per (answer, rubric version, model
version), so a redelivery re-uses the existing evaluation instead of writing a
second one (FR-E6e).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.correlation import correlation
from app.core.logging import get_logger
from app.db.session import sync_session_scope
from app.services.grading import grade_answer
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="app.workers.tasks.grading.grade_answer_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,  # never let retries synchronise into a herd
    max_retries=5,
    acks_late=True,
)
def grade_answer_task(self: Any, answer_id: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    with correlation(session_id=payload.get("session_id")), sync_session_scope() as db:
        try:
            outcome = grade_answer(db, answer_id=uuid.UUID(answer_id))
        except LookupError:
            # A skipped question has no gradable answer. Not an error; not a
            # retry either -- there will never be anything to grade here.
            logger.info("grading_skipped_no_answer", answer_id=answer_id)
            return "skipped"
        return outcome.status.value


@celery_app.task(
    name="app.workers.tasks.grading.publish_session_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def publish_session_task(self: Any, session_id: str, payload: dict[str, Any] | None = None) -> str:
    """Flip a session to ``graded`` once every answered question has a verdict.

    **Per question, not per turn.** A follow-up is another turn on the same
    question, and grading reads the *combined* transcript of all of them, so a
    question yields exactly one evaluation however many turns it took. Counting
    turns instead demanded an evaluation per turn, which meant any question
    with a follow-up could never be satisfied -- the session sat at
    ``completed`` forever and the dashboard said "Grading…" for good.

    Grading only the final turn is also the cheaper answer: grading every
    intermediate turn would pay for the same question twice (§8.3).
    """
    from app.services.grading import publish_session

    with correlation(session_id=session_id), sync_session_scope() as db:
        return publish_session(db, session_id=uuid.UUID(session_id))
