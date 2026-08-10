"""Transactional outbox: write the event in the same transaction as the change.

The failure this prevents (Appendix D.4): under a commit-at-the-seam unit of
work, the service returns *before* the commit. Enqueue a Celery task inside the
service and the worker can pick it up before the row exists; enqueue after the
commit and a crash in between loses the job with no trace.

Writing the event as a row removes the ordering problem entirely -- it commits
atomically with the domain change, and a relay drains it afterwards. Delivery
is at-least-once, which is what you actually get from any queue; the consumers
are idempotent, which is what makes at-least-once safe (NFR-S6).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.correlation import get_request_id
from app.domain.enums import OutboxStatus
from app.models.ops import OutboxEvent

# Event names are part of the contract between API and workers; keep them here.
EVENT_ANSWER_SUBMITTED = "answer.submitted"
EVENT_SESSION_COMPLETED = "session.completed"
EVENT_RESUME_UPLOADED = "resume.uploaded"
EVENT_JD_SUBMITTED = "jd.submitted"
EVENT_SESSION_GRADED = "session.graded"


def enqueue(
    session: AsyncSession | Session,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    """Stage an event. Does **not** commit -- the seam owns that."""
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload or {},
        status=OutboxStatus.PENDING,
        correlation_id=get_request_id(),
    )
    session.add(event)
    return event


def claim_pending(session: Session, limit: int = 50) -> list[OutboxEvent]:
    """Claim a batch for the relay.

    ``FOR UPDATE SKIP LOCKED`` is what lets more than one relay run without
    double-dispatching the same event, and it costs one clause.
    """
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.execute(stmt).scalars().all())
