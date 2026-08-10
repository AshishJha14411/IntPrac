"""The content library: taxonomy + question bank + bank rubrics.

Authored offline, human-reviewed, **never derived from resume or JD prose**
(IR-2 / FR-E1a). This is the half of the schema that lives above the trust
boundary; everything the grader ever sees originates here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPrimaryKey


class Competency(Base, Timestamps):
    """The closed vocabulary referenced by IR-4 (Appendix C.1).

    ``competency_id`` is a human-readable slug on purpose: it appears in
    reduction output, plan slots, and rubric keys, and a readable key makes
    every one of those artefacts debuggable by eye.
    """

    __tablename__ = "competency_taxonomy"

    competency_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    domain: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: ``authored`` (seeded from ``content/taxonomy.py``) or ``inferred``
    #: (registered by plan synthesis when a candidate's documents named a topic
    #: nobody had authored).
    #:
    #: The taxonomy stopped being closed when synthesis arrived, and this column
    #: is how you can still tell what was curated from what a document produced
    #: -- which is the first question to ask of a rubric that reads oddly.
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="authored")

    bank_questions: Mapped[list[BankQuestion]] = relationship(back_populates="competency")


class BankQuestion(Base, UUIDPrimaryKey, Timestamps):
    """One authored question + rubric, keyed by ``(competency_id, seniority)``.

    Versioned: editing a shipped rubric creates a new row with a higher
    ``rubric_version`` (FR-B2d). Past interviews keep pointing at the version
    they were graded against -- scores are never silently rewritten.
    """

    __tablename__ = "question_bank"
    __table_args__ = (
        UniqueConstraint(
            "competency_id",
            "seniority",
            "rubric_version",
            name="uq_question_bank_competency_seniority_version",
        ),
        Index("ix_question_bank_lookup", "competency_id", "seniority", "active"),
    )

    competency_id: Mapped[str] = mapped_column(
        ForeignKey("competency_taxonomy.competency_id", ondelete="RESTRICT"), nullable=False
    )
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rubric_family: Mapped[str] = mapped_column(String(16), nullable=False, default="concept")
    archetype: Mapped[str] = mapped_column(String(24), nullable=False, default="depth")

    #: The bank wording. This is what a candidate hears when no framing applies,
    #: and it is always the fallback if framing sanitisation rejects (FR-M0d).
    neutral_wording: Mapped[str] = mapped_column(Text(), nullable=False)
    #: L1 hint: the same question in different words, zero content added
    #: (FR-E4a). Authored, not generated -- a model rewriting the question at
    #: runtime is exactly how terminology leaks into a hint.
    reframe_wording: Mapped[str | None] = mapped_column(Text())

    #: Estimated answer time, used by the planner to fit a duration budget.
    expected_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    #: True when this rubric was produced by the model rather than authored by
    #: a person. Kept visible because "who wrote the standard you were judged
    #: against" is a fair question, and because it marks what is worth
    #: reviewing and replacing with authored content.
    generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: ``[{"prompt": ..., "targets_concept_id": ...}]`` -- what a real
    #: interviewer asks when an answer is thin, written with the question.
    #:
    #: Cached on the bank question rather than the session, because a follow-up
    #: that probes without naming the concept is the same for every candidate on
    #: that topic; only the opening question is personalised.
    #:
    #: Empty for the authored banks, which fall back to the concept's signpost.
    #: That fallback is *hint* content, so it discloses help and discounts the
    #: candidate's credit (FR-E4f) -- a real follow-up here does not have to.
    followups: Mapped[list[dict[str, str]]] = mapped_column(
        JSONType, nullable=False, default=list
    )

    competency: Mapped[Competency] = relationship(back_populates="bank_questions")
    concepts: Mapped[list[BankRubricConcept]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="BankRubricConcept.ordinal",
    )
    golden_answers: Mapped[list[GoldenAnswer]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class BankRubricConcept(Base, UUIDPrimaryKey, Timestamps):
    """One expected concept (§6.1).

    ``label`` states the *idea in plain language*. FR-B2c is the authoring rule
    that keeps it honest: no label may be satisfiable by naming a term alone.
    """

    __tablename__ = "bank_rubric_concepts"
    __table_args__ = (
        UniqueConstraint("question_id", "concept_id", name="uq_bank_rubric_concepts_concept_id"),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text(), nullable=False)
    weight: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Shown verbatim to the candidate in feedback -- write it for them, not us.
    why_it_matters: Mapped[str] = mapped_column(Text(), nullable=False)
    #: L2 hint: points at the *area to think about* and names no term
    #: (FR-E4b). Authored alongside the concept so the "help with concepts,
    #: not terms" rule is enforced at review time, not hoped for at runtime.
    signpost: Mapped[str | None] = mapped_column(Text())
    #: Paraphrases/analogies that count as understanding (FR-E2a).
    acceptable_signals: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    #: What a wrong mental model looks like -> `contradicted` (FR-E2b).
    common_misconceptions: Mapped[list[str]] = mapped_column(
        JSONType, nullable=False, default=list
    )

    question: Mapped[BankQuestion] = relationship(back_populates="concepts")


class GoldenAnswer(Base, UUIDPrimaryKey, Timestamps):
    """FR-B2e / FR-E6c: every rubric ships with a strong and a weak answer.

    These are the drift gate. A prompt or model change re-scores this set and
    must land inside tolerance or it does not ship.
    """

    __tablename__ = "golden_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(32), nullable=False)  # strong | weak
    transcript: Mapped[str] = mapped_column(Text(), nullable=False)
    #: {concept_id: verdict} -- the human-agreed expectation.
    expected_verdicts: Mapped[dict[str, str]] = mapped_column(
        JSONType, nullable=False, default=dict
    )

    question: Mapped[BankQuestion] = relationship(back_populates="golden_answers")
