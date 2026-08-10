"""Evaluations and concept assessments.

``evaluations`` is **append-only per (answer, rubric_version, model_version)**
-- scores are never mutated in place, so history stays defensible and a re-grade
is a new row rather than an overwrite (§7, FR-E1a).

``concept_assessments`` is the join that makes "what did they miss" a
first-class queryable fact instead of prose buried in a blob.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:  # pragma: no cover
    from app.models.interview import SessionQuestion


class Evaluation(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "evaluations"
    __table_args__ = (
        # FR-E6e: grading is idempotent per (answer, rubric version, model
        # version). At-least-once delivery plus this constraint equals
        # exactly-once effect.
        UniqueConstraint(
            "answer_id",
            "rubric_version",
            "model_version",
            "prompt_version",
            name="uq_evaluations_answer_id",
        ),
        Index("ix_evaluations_question", "session_question_id", "created_at"),
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), nullable=False
    )
    #: Pinned so any score is reproducible and explainable months later (FR-E6b).
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    #: Populated when status == quarantined; the raw output is kept for the
    #: human who has to look at it (FR-E6a).
    quarantine_reason: Mapped[str | None] = mapped_column(Text())
    raw_output: Mapped[dict | None] = mapped_column(JSONType)

    #: Both scores are always kept and both are always shown (FR-E4e).
    raw_score: Mapped[float | None] = mapped_column(Float)
    hint_adjusted_score: Mapped[float | None] = mapped_column(Float)
    #: 1-5 with written anchors, so the scale means the same thing over time.
    band: Mapped[int | None] = mapped_column(Integer)

    #: Informational only, weight zero (FR-E2c). Recorded because it is
    #: interesting feedback, never because it moves a score.
    terminology_notes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessments: Mapped[list[ConceptAssessment]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )
    question: Mapped[SessionQuestion] = relationship(back_populates="evaluations")


class ConceptAssessment(Base, UUIDPrimaryKey, Timestamps):
    """One verdict for one expected concept, with the candidate's own words.

    FR-E2e: a verdict without a quote or an explicit absence marker is invalid
    and triggers a re-grade. ``has_evidence=False`` is the explicit absence
    marker -- it is a legitimate state for `missing`, and an error for anything
    else.
    """

    __tablename__ = "concept_assessments"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "concept_id", name="uq_concept_assessments_evaluation_id"
        ),
    )

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: A quote from the candidate's own words -- not a paraphrase by the grader.
    evidence_quote: Mapped[str | None] = mapped_column(Text())
    has_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Set when a hint touched this concept; used for the hint-adjusted score.
    hint_discounted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: One line the report shows for a gap: what could have been added.
    improvement_note: Mapped[str | None] = mapped_column(Text())

    evaluation: Mapped[Evaluation] = relationship(back_populates="assessments")
