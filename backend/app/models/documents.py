"""Resume and JD intake.

Everything here is **untrusted input** (FR-R8 / NFR-INJ). These tables sit
*below* the trust boundary: their prose feeds exactly one consumer -- the
reduction step -- and is discarded there. No row in this module is ever read by
the planner, the rubric, or the grader.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey


class Resume(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="My resume")

    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", order_by="ResumeVersion.version"
    )


class ResumeVersion(Base, UUIDPrimaryKey, Timestamps):
    """FR-R6: re-upload creates a new version; results never change retroactively."""

    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_id", "version", name="uq_resume_versions_resume_id"),
    )

    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Object-storage key. The file itself never touches the API (FR-R2).
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploaded")
    failure_reason: Mapped[str | None] = mapped_column(Text())
    #: NFR-INJ5 defence-in-depth: instruction-like content found during parse.
    injection_flags: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resume: Mapped[Resume] = relationship(back_populates="versions")
    profile: Mapped[ResumeProfile | None] = relationship(
        back_populates="resume_version", cascade="all, delete-orphan", uselist=False
    )


class ResumeProfile(Base, UUIDPrimaryKey, Timestamps):
    """FR-R4: the structured extraction for one resume version."""

    __tablename__ = "resume_profiles"

    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Identity block, kept separate so it is trivially excludable from anything
    #: downstream (FR-E7c: the grader is name-blind by construction).
    identity: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    raw_text_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: A deterministic rating of how much interview this resume can support,
    #: plus what to add. Feedback for the candidate, never a gate: a sparse
    #: resume still gets a full session (planning tops up), it just also gets
    #: told why the questions drifted from its own content.
    quality: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    resume_version: Mapped[ResumeVersion] = relationship(back_populates="profile")
    items: Mapped[list[ProfileItem]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="ProfileItem.ordinal"
    )


class ProfileItem(Base, UUIDPrimaryKey, Timestamps):
    """FR-R5: every extracted item carries the source span it came from.

    Provenance is what lets a question cite the exact bullet it is probing, and
    what lets a human see the extraction wasn't invented.
    """

    __tablename__ = "profile_items"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    source_text: Mapped[str] = mapped_column(Text(), nullable=False)
    source_span_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_span_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: FR-R3 recency weighting (FR-M-A3); higher = more recent/prominent.
    prominence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: FR-R7: candidate corrections land as an overlay, never a destructive edit.
    corrected_payload: Mapped[dict | None] = mapped_column(JSONType)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[ResumeProfile] = relationship(back_populates="items")


class JobDescription(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "job_descriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    versions: Mapped[list[JDVersion]] = relationship(
        back_populates="job_description",
        cascade="all, delete-orphan",
        order_by="JDVersion.version",
    )


class JDVersion(Base, UUIDPrimaryKey, Timestamps):
    """FR-J3: JDs are reusable across candidates and versioned like resumes."""

    __tablename__ = "jd_versions"
    __table_args__ = (
        UniqueConstraint("job_description_id", "version", name="uq_jd_versions_job_description_id"),
    )

    job_description_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="paste")
    raw_text: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploaded")
    failure_reason: Mapped[str | None] = mapped_column(Text())
    injection_flags: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    #: FR-J4: a thin JD warns rather than silently producing a weak interview.
    thin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job_description: Mapped[JobDescription] = relationship(back_populates="versions")
    profile: Mapped[JDProfile | None] = relationship(
        back_populates="jd_version", cascade="all, delete-orphan", uselist=False
    )


class JDProfile(Base, UUIDPrimaryKey, Timestamps):
    """FR-J2."""

    __tablename__ = "jd_profiles"

    jd_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jd_versions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    role_title: Mapped[str | None] = mapped_column(String(200))
    #: Seniority is taken from the JD or set by HR -- never inferred from the
    #: resume, which would reintroduce resume influence on the standard (§12.5).
    seniority: Mapped[str | None] = mapped_column(String(16))
    domain: Mapped[str | None] = mapped_column(String(48))
    responsibilities: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)

    jd_version: Mapped[JDVersion] = relationship(back_populates="profile")
    requirements: Mapped[list[JDRequirement]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="JDRequirement.ordinal"
    )


class JDRequirement(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "jd_requirements"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jd_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Validated against the closed taxonomy; anything else is dropped (IR-4).
    competency_id: Mapped[str] = mapped_column(
        ForeignKey("competency_taxonomy.competency_id", ondelete="RESTRICT"), nullable=False
    )
    weight: Mapped[str] = mapped_column(String(16), nullable=False, default="required")
    source_text: Mapped[str] = mapped_column(Text(), nullable=False, default="")

    profile: Mapped[JDProfile] = relationship(back_populates="requirements")
