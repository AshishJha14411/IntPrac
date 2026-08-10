"""The interview session and everything the trust boundary produces.

Read this file top-to-bottom and the boundary (§1.2) is visible in the schema
itself:

* ``ReductionResult`` is the *only* row that crosses it, and it holds nothing
  but enums.
* ``SessionQuestion.framing_text`` is cosmetic, sanitised, and carries a comment
  saying it never reaches the grader (FR-M0c).
* ``SessionQuestion.source_profile_item_id`` is a **link, not prose** -- enough
  to derive `unsubstantiated_claim` after the fact (FR-M-A4) without ever
  letting the claim influence the score.
* ``RubricConcept`` rows are *copied from the bank at plan time*, so a later
  bank edit cannot retroactively move the bar a candidate was measured against.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:  # pragma: no cover - resolved by SQLAlchemy at mapper config time
    from app.models.evaluation import Evaluation


class Posting(Base, UUIDPrimaryKey, Timestamps):
    """Official-mode container. Practice sessions leave ``posting_id`` null."""

    __tablename__ = "postings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    jd_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jd_versions.id", ondelete="SET NULL")
    )
    #: FR-P3: the saved plan template every candidate for this posting gets, so
    #: FR-P4 comparability holds by construction rather than by good intentions.
    template: Mapped[dict | None] = mapped_column(JSONType)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InterviewSession(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        Index("ix_interview_sessions_user_created", "user_id", "created_at"),
        Index("ix_interview_sessions_posting_status", "posting_id", "status"),
    )
    #: Optimistic locking (Appendix D.3). Two tabs advancing the same session
    #: would otherwise silently lose one update; instead the second write hits
    #: a StaleDataError, which the error layer turns into a 409 "refresh and
    #: retry". Configured via ``__mapper_args__`` below.
    #: SQLAlchemy bumps this on every flush and adds it to the UPDATE's WHERE
    #: clause, so a concurrent write matches zero rows and raises StaleDataError.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": lock_version}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    posting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("postings.id", ondelete="SET NULL")
    )

    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="practice")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created", index=True)

    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    #: The seniority the *rubrics* are keyed to. Set by JD/HR in official mode,
    #: chosen by the candidate in practice mode -- never inferred from a resume.
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(48))

    #: Inputs, kept as links so we can show provenance in the UI. Nothing
    #: downstream of planning reads their prose.
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    jd_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jd_versions.id", ondelete="SET NULL")
    )

    current_question_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: FR-S11: invisible to scoring, disclosed to HR only as "accommodation
    #: applied" -- never with medical detail.
    accommodation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list[SessionQuestion]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionQuestion.ordinal",
    )
    reduction: Mapped[ReductionResult | None] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )
    fit_map: Mapped[list[FitMapEntry]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ReductionResult(Base, UUIDPrimaryKey, Timestamps):
    """═══ THE TRUST BOUNDARY OUTPUT (§1.2) ═══

    This row is the entire contract between "untrusted documents" and
    "everything that decides a rating". It holds a validated, closed-vocabulary
    selector set and **nothing else** -- no prose, no names, no free text.

    The worst a hostile resume can achieve is a wrong list of
    ``competency_ids``: a quality bug, never a scoring compromise (NFR-INJ1).
    """

    __tablename__ = "reduction_results"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Every entry is validated against ``competency_taxonomy`` (IR-4).
    competency_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Candidates the reducer proposed that were *not* in the taxonomy. Kept for
    #: observability (a spike means the bank has a gap), never for selection.
    discarded_candidates: Mapped[list[str]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="rules-v1")

    session: Mapped[InterviewSession] = relationship(back_populates="reduction")


class SessionQuestion(Base, UUIDPrimaryKey, Timestamps):
    """A planned question slot, resolved against the bank at plan time (FR-P5)."""

    __tablename__ = "session_questions"
    __table_args__ = (
        UniqueConstraint("session_id", "ordinal", name="uq_session_questions_session_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    competency_id: Mapped[str] = mapped_column(
        ForeignKey("competency_taxonomy.competency_id", ondelete="RESTRICT"), nullable=False
    )
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    bank_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank.id", ondelete="RESTRICT"), nullable=False
    )
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_family: Mapped[str] = mapped_column(String(16), nullable=False, default="concept")

    #: The standard. Identical for every candidate at this (competency,
    #: seniority) -- FR-M0b.
    neutral_wording: Mapped[str] = mapped_column(Text(), nullable=False)
    #: Frozen L1 hint copy (FR-E4a).
    reframe_wording: Mapped[str | None] = mapped_column(Text())
    #: ⚠ COSMETIC ONLY. Sanitised, length-capped, and never passed to the
    #: grader (FR-M0c). If sanitisation rejects it this stays null and the
    #: neutral wording is used (FR-M0d).
    framing_text: Mapped[str | None] = mapped_column(Text())
    #: A link, not prose (FR-M-A4). Enough to join "this topic came from resume
    #: item Y" *after* grading, so `unsubstantiated_claim` is a derived fact
    #: rather than a grader judgement.
    source_profile_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile_items.id", ondelete="SET NULL")
    )
    #: Frozen copy of the bank question's follow-ups, for the same reason the
    #: rubric is frozen (FR-P5): re-versioning the bank tomorrow must not change
    #: what a live interview asks. Copying also keeps the turn loop off the
    #: `bank_question` relationship, which would be lazy IO after an await --
    #: `MissingGreenlet` in production and nowhere else (Appendix D.4).
    #:
    #: Empty for authored questions, which fall back to the concept signpost.
    followups: Mapped[list[dict[str, str]]] = mapped_column(
        JSONType, nullable=False, default=list
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    followup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    session: Mapped[InterviewSession] = relationship(back_populates="questions")
    concepts: Mapped[list[RubricConcept]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="RubricConcept.ordinal"
    )
    answers: Mapped[list[Answer]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="Answer.turn_index"
    )
    hints: Mapped[list[Hint]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="Hint.created_at"
    )
    #: Append-only: a re-grade adds a row, it never overwrites one.
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )

    @property
    def prompt(self) -> str:
        """What the candidate actually sees."""
        return self.framing_text or self.neutral_wording


class RubricConcept(Base, UUIDPrimaryKey, Timestamps):
    """A frozen copy of one bank concept, bound to this question (§6.1).

    Copied rather than referenced so that re-versioning the bank tomorrow
    cannot change what a candidate was graded against yesterday.
    """

    __tablename__ = "rubric_concepts"
    __table_args__ = (
        UniqueConstraint(
            "session_question_id", "concept_id", name="uq_rubric_concepts_session_question_id"
        ),
    )

    session_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text(), nullable=False)
    weight: Mapped[str] = mapped_column(String(16), nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text(), nullable=False)
    #: Frozen L2 hint copy -- names the area, never the term (FR-E4b).
    signpost: Mapped[str | None] = mapped_column(Text())
    acceptable_signals: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    common_misconceptions: Mapped[list[str]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    #: Set when a hint touched this concept, so credit can be reduced on *this*
    #: concept rather than on the whole answer (FR-E4e).
    hint_touched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    question: Mapped[SessionQuestion] = relationship(back_populates="concepts")


class Answer(Base, UUIDPrimaryKey, Timestamps):
    """One turn of the candidate's response.

    ``turn_index`` 0 is the answer to the question; 1..2 are answers to
    follow-ups. Follow-ups stay inside the question's existing rubric, so they
    are turns of the same answer rather than new questions (FR-E5b).
    """

    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint(
            "session_question_id", "turn_index", name="uq_answers_session_question_id"
        ),
        # FR-S8: a retried submit must never double-record.
        UniqueConstraint("idempotency_key", name="uq_answers_idempotency_key"),
    )

    session_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Null for the main answer; the follow-up prompt for turns >= 1.
    prompt_text: Mapped[str | None] = mapped_column(Text())
    transcript: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    input_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="typed")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    #: FR-S6: a skip is recorded as skipped, not as wrong.
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    question: Mapped[SessionQuestion] = relationship(back_populates="answers")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="answer", cascade="all, delete-orphan", order_by="TranscriptSegment.ordinal"
    )


class TranscriptSegment(Base, UUIDPrimaryKey, Timestamps):
    """FR-V2/V3/V4. Populated by the voice pipeline in P1; unused in text mode.

    Timings align to the media timeline, which is what powers HR's "jump to
    this answer". Low-confidence spans are marked, never silently guessed at.
    """

    __tablename__ = "transcript_segments"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float | None] = mapped_column()
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    answer: Mapped[Answer] = relationship(back_populates="segments")


class Hint(Base, UUIDPrimaryKey, Timestamps):
    """FR-E4d: every hint recorded with level, trigger, timestamp and text."""

    __tablename__ = "hints"

    session_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(24), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    #: Which concepts this hint pointed at -- the scope of the credit reduction.
    touched_concept_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)

    question: Mapped[SessionQuestion] = relationship(back_populates="hints")


class FitMapEntry(Base, UUIDPrimaryKey, Timestamps):
    """FR-M-C1..C3: per-JD-competency evidence classification for mode C.

    Shown to HR to explain *why each question was asked*. `absent` drives an
    assess-learnability question, never a punishment.
    """

    __tablename__ = "fit_map_entries"
    __table_args__ = (
        UniqueConstraint("session_id", "competency_id", name="uq_fit_map_entries_session_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competency_id: Mapped[str] = mapped_column(
        ForeignKey("competency_taxonomy.competency_id", ondelete="RESTRICT"), nullable=False
    )
    fit: Mapped[str] = mapped_column(String(16), nullable=False)
    jd_weight: Mapped[str] = mapped_column(String(16), nullable=False, default="required")
    #: Evidence is a list of profile-item ids -- links, not prose.
    evidence_item_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)

    session: Mapped[InterviewSession] = relationship(back_populates="fit_map")
