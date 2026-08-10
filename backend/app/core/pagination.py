"""Keyset pagination for growing lists (Appendix D.2).

The compound key is ``(created_at, id)``. The id tiebreaker is what makes the
ordering *total* -- without it, rows sharing a timestamp repeat or vanish across
pages, which is the same class of bug the pagination rubric in the question bank
asks candidates about.

Cursors are opaque base64 and validated on the way in; tampering yields a clean
422, never a 500.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import Select, and_, or_

from app.core.errors import ValidationError

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class Cursor:
    created_at: datetime
    id: uuid.UUID

    def encode(self) -> str:
        raw = json.dumps({"c": self.created_at.isoformat(), "i": str(self.id)})
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> Cursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()))
            return cls(created_at=datetime.fromisoformat(data["c"]), id=uuid.UUID(data["i"]))
        except (binascii.Error, ValueError, KeyError, TypeError) as exc:
            raise ValidationError("Malformed pagination cursor.") from exc


@dataclass(slots=True)
class Page[T]:
    items: Sequence[T]
    next_cursor: str | None

    def to_dict(self, serializer: Any) -> dict[str, Any]:
        return {
            "items": [serializer(item) for item in self.items],
            "next_cursor": self.next_cursor,
        }


def apply_keyset(stmt: Select[Any], model: Any, cursor: str | None, limit: int) -> Select[Any]:
    """Newest-first keyset window. Seeks by the last-seen key, never OFFSET."""
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc())
    if cursor:
        decoded = Cursor.decode(cursor)
        stmt = stmt.where(
            or_(
                model.created_at < decoded.created_at,
                and_(model.created_at == decoded.created_at, model.id < decoded.id),
            )
        )
    return stmt.limit(limit + 1)  # +1 sentinel tells us whether a next page exists


def finish_page(rows: Sequence[Any], limit: int) -> Page[Any]:
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        return Page(items=rows, next_cursor=Cursor(last.created_at, last.id).encode())
    return Page(items=rows, next_cursor=None)


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(limit, MAX_PAGE_SIZE))
