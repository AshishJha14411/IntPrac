"""Cross-cutting operational tables: outbox, cost, audit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey


class OutboxEvent(Base, UUIDPrimaryKey, Timestamps):
    """Transactional outbox (NFR-S6, Appendix D.4).

    The problem it solves: under a commit-at-the-seam unit of work, the commit
    happens *after* the service returns. Enqueue inside the service and the
    worker races a row that does not exist yet; enqueue after and a crash
    between commit and enqueue loses the job silently.

    Writing the event in the same transaction as the domain change removes the
    race entirely -- a relay drains this table afterwards, at-least-once, into
    idempotent consumers.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_unpublished", "status", "created_at"),)

    aggregate_type: Mapped[str] = mapped_column(String(48), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text())
    #: Carried through so a worker log line joins to the request that caused it.
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class UsageCost(Base, UUIDPrimaryKey, Timestamps):
    """NFR-C1: a session whose cost is unknown is a bug.

    Recorded from day one because retrofitting attribution is painful
    (Appendix D.8) -- and because at this scale cost is a design constraint,
    not a dashboard metric.
    """

    __tablename__ = "usage_costs"
    __table_args__ = (
        Index("ix_usage_costs_user_created", "user_id", "created_at"),
        Index("ix_usage_costs_session", "session_id"),
    )

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vendor: Mapped[str] = mapped_column(String(32), nullable=False, default="google")
    model: Mapped[str | None] = mapped_column(String(64))


class AuditLog(Base, UUIDPrimaryKey, Timestamps):
    """FR-H9 / NFR-SEC: who viewed, who rated, what changed, when."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_resource", "resource_type", "resource_id", "created_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
