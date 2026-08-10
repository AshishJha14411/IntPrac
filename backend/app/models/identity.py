"""Users, orgs, and session tokens.

Multi-tenancy note (Appendix D.9): every domain row carries an
``organization_id`` so org scoping stays *possible*, but we are deliberately
not building the org-management product at this scale. A personal org is
created for each user at registration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey


class Organization(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    is_personal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: NFR-P retention policy, per org, with a hard default.
    # Six months for both (G-009). Consent used to promise 24 months while
    # nothing deleted transcripts at all, which is the worst combination:
    # a long promise and no mechanism. A shorter window that is actually
    # enforced is both more honest and less to hold -- this data is video,
    # voice and resumes, among the most sensitive categories there is (NFR-P).
    media_retention_days: Mapped[int] = mapped_column(nullable=False, default=180)
    transcript_retention_days: Mapped[int] = mapped_column(nullable=False, default=180)
    #: FR-F6: none | after_decision | always
    candidate_feedback_visibility: Mapped[str] = mapped_column(
        String(24), nullable=False, default="after_decision"
    )

    members: Mapped[list[OrgMember]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base, UUIDPrimaryKey, Timestamps):
    """A global identity that can be linked to many orgs (§3)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    #: Argon2id. Nullable for OAuth-only accounts (FR-A1).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: NFR-P: training on candidate data is off by default and opt-in only.
    training_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    memberships: Mapped[list[OrgMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class OrgMember(Base, UUIDPrimaryKey, Timestamps):
    """FR-A4: role assignment is per-org, never global."""

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_members_organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class RefreshToken(Base, UUIDPrimaryKey, Timestamps):
    """FR-A3: rotating refresh tokens with reuse detection.

    Rotation alone is not the protection -- *detecting the reuse of an already
    rotated token* is. When that happens the whole family is revoked, because
    the only explanation is that a token leaked.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: All rotations of one login share a family id.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    #: SHA-256 of the presented token. We never store the token itself.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class Consent(Base, UUIDPrimaryKey, Timestamps):
    """FR-S2: timestamped, versioned, and a hard gate on any capture."""

    __tablename__ = "consents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    consent_version: Mapped[str] = mapped_column(String(24), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The exact disclosure text shown, so we can prove what was agreed to.
    disclosures: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
