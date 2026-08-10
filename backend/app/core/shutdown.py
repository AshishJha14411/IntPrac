"""Graceful shutdown that does not kill a live interview (NFR-S3).

This is the reliability requirement most specific to this product. A routine
deploy silently destroying someone's 25-minute interview is the worst failure
mode in the system, and it is entirely preventable:

* On SIGTERM the instance stops accepting **new** sessions (readiness goes
  false, so the load balancer drains it) ...
* ... but keeps existing sessions alive until they complete or hit the drain
  deadline ...
* ... and if the deadline is hit, the client is told to reconnect and resumes
  at the current question (FR-S8) rather than losing the session.

The counter is deliberately in-process: at one-instance scale that is the
correct scope, and a distributed version would be architecture theatre (§2.2).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.logging import get_logger

logger = get_logger(__name__)

DRAIN_DEADLINE_SECONDS = 30.0


class DrainGuard:
    def __init__(self) -> None:
        self._active = 0
        self._draining = False
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def draining(self) -> bool:
        return self._draining

    @property
    def active_sessions(self) -> int:
        return self._active

    def accepting_new_work(self) -> bool:
        return not self._draining

    @asynccontextmanager
    async def track(self) -> AsyncIterator[None]:
        """Wrap a live session turn so shutdown waits for it."""
        self._active += 1
        self._idle.clear()
        try:
            yield
        finally:
            self._active -= 1
            if self._active <= 0:
                self._active = 0
                self._idle.set()

    async def drain(self, deadline: float = DRAIN_DEADLINE_SECONDS) -> bool:
        """Stop taking new sessions and wait for in-flight ones.

        Returns ``True`` if everything finished cleanly, ``False`` if the
        deadline forced us out (in which case clients reconnect and resume).
        """
        self._draining = True
        if self._active == 0:
            return True
        logger.info("draining_sessions", active=self._active, deadline_seconds=deadline)
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=deadline)
        except TimeoutError:
            logger.warning("drain_deadline_hit", still_active=self._active)
            return False
        logger.info("drain_complete")
        return True

    def reset(self) -> None:
        """Test hook.

        In production one process serves one app for its lifetime, so draining
        is a one-way door and that is correct. Tests build many apps in one
        process, so they need a way back.
        """
        self._draining = False
        self._active = 0
        self._idle.set()


drain_guard = DrainGuard()
