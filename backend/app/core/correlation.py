"""Correlation ids propagated API -> service -> worker -> vendor call (NFR-O).

Kept in contextvars so nothing has to thread an id through every signature, and
so Celery tasks can re-bind the id they were dispatched with.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"


def new_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_session_id() -> str | None:
    return _session_id.get()


def set_session_id(value: str | None) -> None:
    _session_id.set(value)


@contextmanager
def correlation(request_id: str | None = None, session_id: str | None = None) -> Iterator[str]:
    """Bind correlation ids for a block of work (used by Celery tasks)."""
    rid = request_id or new_id()
    request_token = _request_id.set(rid)
    session_token = _session_id.set(session_id)
    try:
        yield rid
    finally:
        _request_id.reset(request_token)
        _session_id.reset(session_token)


def current_context() -> dict[str, str]:
    ctx: dict[str, str] = {}
    if rid := _request_id.get():
        ctx["request_id"] = rid
    if sid := _session_id.get():
        ctx["session_id"] = sid
    return ctx
