"""The outbox relay: turn committed events into dispatched work.

Runs on a short beat. Claiming with ``FOR UPDATE SKIP LOCKED`` means two relays
can run concurrently without double-dispatching, and marking the row published
in the *same* transaction as the dispatch keeps the two facts consistent.

Delivery is at-least-once, so a duplicate dispatch is expected and harmless --
every consumer downstream is idempotent.

**In workerless mode (ADR 010)** the same function is called directly by the
request that just committed, and ``.delay()`` executes the task inline rather
than handing it to a broker. Two things follow, both handled below: the relay
has to check whether the inline run actually *succeeded* before writing the row
off as published, and it has to stop at a time budget so a request cannot be
held open indefinitely.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.correlation import correlation
from app.core.logging import get_logger
from app.db.session import sync_session_scope
from app.domain.enums import OutboxStatus
from app.services import outbox
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

MAX_ATTEMPTS = 8


class InlineTaskFailed(RuntimeError):
    """An eagerly-executed task did not reach ``SUCCESS``.

    Raised so the failure lands in the same handler a broker-dispatch failure
    would, which is what keeps the retry ledger honest in both modes.
    """


def _handlers() -> dict[str, Any]:
    from app.workers.tasks.grading import grade_answer_task, publish_session_task
    from app.workers.tasks.parsing import parse_jd_task, parse_resume_task

    return {
        outbox.EVENT_ANSWER_SUBMITTED: grade_answer_task,
        outbox.EVENT_SESSION_COMPLETED: publish_session_task,
        outbox.EVENT_RESUME_UPLOADED: parse_resume_task,
        outbox.EVENT_JD_SUBMITTED: parse_jd_task,
    }


@celery_app.task(name="app.workers.tasks.outbox.drain_outbox")
def drain_outbox(batch_size: int = 50, budget_seconds: float | None = None) -> int:
    handlers = _handlers()
    eager = bool(celery_app.conf.task_always_eager)
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds

    dispatched = 0
    with sync_session_scope() as db:
        for event in outbox.claim_pending(db, batch_size):
            # Checked before starting an event, never mid-flight: a request can
            # absorb one over-budget task but not a queue of them. Anything left
            # stays pending, which is exactly the state it was already in.
            if deadline is not None and time.monotonic() >= deadline:
                break

            task = handlers.get(event.event_type)
            if task is None:
                event.status = OutboxStatus.FAILED
                event.last_error = f"no handler for '{event.event_type}'"
                continue
            try:
                with correlation(event.correlation_id):
                    result = task.delay(str(event.aggregate_id), event.payload)
                # Workerless mode: `.delay()` has already *run* the task, and
                # `task_eager_propagates=False` turned any failure into a
                # result rather than an exception. Marking such an event
                # published would drop the work on the floor with a 200 in the
                # access log and nothing else -- so ask the result. Note this is
                # `successful()` rather than `not failed()`: a task that called
                # `self.retry()` lands in RETRY, which nothing will ever pick up
                # again once eager mode has removed the broker.
                if eager and not result.successful():
                    raise InlineTaskFailed(f"{event.event_type}: {result.result}")
                event.status = OutboxStatus.PUBLISHED
                event.published_at = datetime.now(UTC)
                dispatched += 1
            except Exception as exc:
                # The row stays PENDING, so the next drain retries it. With no
                # broker there is no other retry mechanism, which makes this
                # ledger -- attempts, last_error, MAX_ATTEMPTS -- the whole of
                # it. It was already here for the broker's benefit; workerless
                # mode just leans on it harder.
                event.attempts += 1
                event.last_error = str(exc)[:500]
                if event.attempts >= MAX_ATTEMPTS:
                    # Stop retrying, keep the row. A dead event is a bug to
                    # look at, not garbage to collect.
                    event.status = OutboxStatus.FAILED
                    logger.error(
                        "outbox_event_dead", event_id=str(event.id), event_type=event.event_type
                    )
    if dispatched:
        logger.info("outbox_drained", dispatched=dispatched)
    return dispatched


@celery_app.task(name="app.workers.tasks.outbox.replay_failed")
def replay_failed(event_id: str) -> bool:
    """Operator hook: put a dead event back in the queue after a fix."""
    with sync_session_scope() as db:
        from app.models.ops import OutboxEvent

        event = db.get(OutboxEvent, uuid.UUID(event_id))
        if event is None:
            return False
        event.status = OutboxStatus.PENDING
        event.attempts = 0
        event.last_error = None
        return True
