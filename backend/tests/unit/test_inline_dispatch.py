"""ADR 010 -- running background work without a worker process.

The whole risk of workerless mode is that its failures are *quiet*. A missing
worker doesn't 500; events queue, the API keeps returning 200, and nothing is
ever graded. v1 shipped exactly that bug. So these tests are all shaped the
same way: assert that work is never written off as done when it wasn't.

No services needed -- the relay's collaborators are stubbed, which is the point.
The relay's contract is "decide what happens to the row", and that decision is
what these pin.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.domain.enums import OutboxStatus
from app.services import dispatch, outbox
from app.workers.celery_app import celery_app
from app.workers.tasks import outbox as relay


class FakeEvent:
    """Just the columns the relay touches."""

    def __init__(self, event_type: str) -> None:
        self.id = uuid.uuid4()
        self.aggregate_id = uuid.uuid4()
        self.event_type = event_type
        self.payload: dict[str, Any] = {}
        self.correlation_id = None
        self.status = OutboxStatus.PENDING
        self.attempts = 0
        self.last_error: str | None = None
        self.published_at = None


class FakeResult:
    """Stands in for Celery's ``EagerResult``."""

    def __init__(self, state: str, value: Any = None) -> None:
        self._state = state
        self.result = value

    def successful(self) -> bool:
        return self._state == "SUCCESS"


class FakeTask:
    def __init__(self, result: FakeResult, delay_seconds: float = 0.0) -> None:
        self._result = result
        self._delay_seconds = delay_seconds
        self.calls = 0

    def delay(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        self.calls += 1
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        return self._result


@contextmanager
def _dispatch_mode(always_eager: bool) -> Iterator[None]:
    """Pin the mode for a test.

    Both fixtures set the flag rather than inheriting it: the app-level default
    comes from the environment, so a developer with `CELERY_TASK_ALWAYS_EAGER`
    in their gitignored `.env` would otherwise silently run half these tests
    against the wrong mode.
    """
    previous = celery_app.conf.task_always_eager
    celery_app.conf.update(task_always_eager=always_eager)
    try:
        yield
    finally:
        celery_app.conf.update(task_always_eager=previous)


@pytest.fixture
def eager() -> Iterator[None]:
    with _dispatch_mode(True):
        yield


@pytest.fixture
def broker() -> Iterator[None]:
    with _dispatch_mode(False):
        yield


@pytest.fixture
def relay_harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire the relay to in-memory events and hand back a setter for handlers."""
    events: list[FakeEvent] = []
    handlers: dict[str, Any] = {}

    @contextmanager
    def fake_scope() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(relay, "sync_session_scope", fake_scope)
    monkeypatch.setattr(relay, "_handlers", lambda: handlers)
    monkeypatch.setattr(outbox, "claim_pending", lambda _db, _limit: list(events))

    return SimpleNamespace(events=events, handlers=handlers)


def test_a_successful_inline_run_publishes_the_event(eager: None, relay_harness: Any) -> None:
    event = FakeEvent(outbox.EVENT_ANSWER_SUBMITTED)
    relay_harness.events.append(event)
    relay_harness.handlers[event.event_type] = FakeTask(FakeResult("SUCCESS", "complete"))

    assert relay.drain_outbox() == 1
    assert event.status == OutboxStatus.PUBLISHED
    assert event.published_at is not None


def test_a_failed_inline_run_leaves_the_event_pending(eager: None, relay_harness: Any) -> None:
    """The one that matters.

    ``task_eager_propagates=False`` means a failing task comes back as a
    *result*, not an exception. A relay that only watched for exceptions would
    mark the row published and the answer would never be graded -- silently,
    with a 200 in the access log. With no broker, this ledger is the only retry
    mechanism there is.
    """
    event = FakeEvent(outbox.EVENT_ANSWER_SUBMITTED)
    relay_harness.events.append(event)
    relay_harness.handlers[event.event_type] = FakeTask(
        FakeResult("FAILURE", RuntimeError("gemini 503"))
    )

    assert relay.drain_outbox() == 0
    assert event.status == OutboxStatus.PENDING
    assert event.attempts == 1
    assert "503" in (event.last_error or "")


def test_a_retrying_task_is_not_treated_as_published(eager: None, relay_harness: Any) -> None:
    """RETRY is not FAILURE, and in eager mode nothing will ever re-run it.

    ``publish_session_task`` re-queues itself while any answer is still
    ungraded. Under a broker that is correct; with eager mode there is no broker
    to hold the retry, so a check of ``failed()`` would pass it through as
    success and the session would never reach ``published``.
    """
    event = FakeEvent(outbox.EVENT_SESSION_COMPLETED)
    relay_harness.events.append(event)
    relay_harness.handlers[event.event_type] = FakeTask(FakeResult("RETRY", "answers pending"))

    assert relay.drain_outbox() == 0
    assert event.status == OutboxStatus.PENDING
    assert event.attempts == 1


def test_the_ledger_gives_up_eventually_rather_than_looping_forever(
    eager: None, relay_harness: Any
) -> None:
    event = FakeEvent(outbox.EVENT_ANSWER_SUBMITTED)
    event.attempts = relay.MAX_ATTEMPTS - 1
    relay_harness.events.append(event)
    relay_harness.handlers[event.event_type] = FakeTask(FakeResult("FAILURE", RuntimeError("nope")))

    relay.drain_outbox()
    # Dead, but still on the table -- a dead event is a bug to look at.
    assert event.status == OutboxStatus.FAILED


def test_the_budget_stops_the_drain_between_events(eager: None, relay_harness: Any) -> None:
    """A request may absorb one over-budget task, never a queue of them."""
    slow = FakeEvent(outbox.EVENT_ANSWER_SUBMITTED)
    second = FakeEvent(outbox.EVENT_RESUME_UPLOADED)
    relay_harness.events.extend([slow, second])
    slow_task = FakeTask(FakeResult("SUCCESS"), delay_seconds=0.05)
    next_task = FakeTask(FakeResult("SUCCESS"))
    relay_harness.handlers[slow.event_type] = slow_task
    relay_harness.handlers[second.event_type] = next_task

    relay.drain_outbox(budget_seconds=0.01)

    assert slow_task.calls == 1
    assert next_task.calls == 0, "the budget is checked before starting an event, not mid-flight"
    assert second.status == OutboxStatus.PENDING, "skipped work stays claimable"


def test_broker_mode_does_not_interrogate_the_result(broker: None, relay_harness: Any) -> None:
    """``successful()`` against a real backend is a network call per dispatch.

    With a worker running, a dispatch that returned is a dispatch that worked;
    the task's own outcome is the worker's business.
    """
    event = FakeEvent(outbox.EVENT_ANSWER_SUBMITTED)
    relay_harness.events.append(event)

    class ExplodingResult(FakeResult):
        def successful(self) -> bool:
            raise AssertionError("the relay must not poll the result backend in broker mode")

    relay_harness.handlers[event.event_type] = FakeTask(ExplodingResult("SUCCESS"))

    assert relay.drain_outbox() == 1
    assert event.status == OutboxStatus.PUBLISHED


# ---------------------------------------------------------------------------
# The seam, and the flag
# ---------------------------------------------------------------------------
def test_the_flag_alone_is_never_enough_the_seam_has_to_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the exact trap ADR 010 documents.

    Nothing in this codebase calls ``.delay()`` directly -- writes stage an
    outbox row, and beat is what drains it. Turn eager mode on, delete the
    worker *and* beat, and without this call every event sits at ``pending``
    forever while the API returns 200s. So: the seam drains, on every request
    that committed, or workerless mode is a silent data-loss switch.
    """
    import app.db.session as db_session

    class FakeSession:
        def __init__(self) -> None:
            self.committed = False

        async def commit(self) -> None:
            self.committed = True

        async def rollback(self) -> None: ...

        async def close(self) -> None: ...

    drained: list[bool] = []

    async def fake_drain() -> None:
        drained.append(True)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(db_session.dispatch, "drain_after_commit", fake_drain)

    async def drive() -> None:
        generator = db_session.get_session()
        session = await anext(generator)
        assert isinstance(session, FakeSession)
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        assert session.committed, "the seam owns the commit"

    import asyncio

    asyncio.run(drive())
    assert drained == [True], "a committed request must drain the outbox"


def test_a_failed_request_does_not_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing committed, so there is nothing legitimate to dispatch."""
    import asyncio

    import app.db.session as db_session

    class FakeSession:
        async def commit(self) -> None: ...

        async def rollback(self) -> None:
            self.rolled_back = True

        async def close(self) -> None: ...

    drained: list[bool] = []

    async def fake_drain() -> None:
        drained.append(True)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(db_session.dispatch, "drain_after_commit", fake_drain)

    async def drive() -> None:
        generator = db_session.get_session()
        await anext(generator)
        with pytest.raises(ValueError, match="boom"):
            await generator.athrow(ValueError("boom"))

    asyncio.run(drive())
    assert drained == []


@pytest.mark.parametrize(
    ("eager_flag", "budget", "expected"),
    [
        (False, 10.0, False),  # a worker is running; the relay is beat's job
        (True, 10.0, True),
        (True, 0.0, False),  # explicit opt-out
    ],
)
def test_inline_dispatch_is_enabled_only_when_it_has_to_be(
    eager_flag: bool, budget: float, expected: bool
) -> None:
    settings = Settings(
        celery_task_always_eager=eager_flag, inline_drain_budget_seconds=budget
    )
    assert settings.inline_dispatch_enabled is expected


def test_dispatch_mode_is_reported_not_inferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/health/ready`` answers "is a worker expected here?" without a console."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "celery_task_always_eager", True)
    assert dispatch.dispatch_mode() == "inline"
    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    assert dispatch.dispatch_mode() == "worker"
