"""Interview session contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    AnswerInputMode,
    Domain,
    HintTrigger,
    InterviewMode,
    Seniority,
    SessionPurpose,
)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: InterviewMode
    #: Set by the candidate in practice mode, by the JD/reviewer in official
    #: mode -- never inferred from a resume (§12.5).
    seniority: Seniority
    purpose: SessionPurpose = SessionPurpose.PRACTICE
    target_minutes: int = Field(default=20, ge=5, le=60)
    domain: Domain | None = None
    resume_version_id: uuid.UUID | None = None
    jd_version_id: uuid.UUID | None = None
    accommodation: bool = False


class PlannedQuestionResponse(BaseModel):
    """FR-P3: the plan is reviewable *before* the session starts.

    Reviewable means "these are the topics", not "here is the mark scheme".

    ``concept_count``/``core_concept_count`` used to ship here and were a quiet
    leak: knowing a question has four core concepts tells you how many distinct
    points to make, which is a hint nobody asked for and which the hint ladder
    would otherwise charge for. Worse, it varies per question, so a candidate
    could pace themselves against the rubric's shape.

    ``prompt`` stays: seeing the questions in advance is the point of FR-P3 --
    the candidate agreeing to what they will be asked. The *standard* behind
    each one is not part of that agreement, and arrives with the report.
    """

    id: uuid.UUID
    ordinal: int
    competency_id: str
    prompt: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    mode: str
    purpose: str
    seniority: str
    target_minutes: int
    question_count: int
    created_at: datetime
    completed_at: datetime | None = None


class SessionPlanResponse(BaseModel):
    session: SessionResponse
    questions: list[PlannedQuestionResponse]
    competencies: list[str]
    #: Selector candidates dropped for not being in the taxonomy (IR-4).
    discarded_candidates: list[str] = Field(default_factory=list)


class ConsentRequest(BaseModel):
    """FR-S2. No consent -> no recording, no session."""

    model_config = ConfigDict(extra="forbid")

    consent_version: str = Field(default="2026-07-01", max_length=24)
    accepts_ai_assessment: bool
    accepts_recording: bool
    accepts_retention: bool

    def all_accepted(self) -> bool:
        return self.accepts_ai_assessment and self.accepts_recording and self.accepts_retention


class TurnResponse(BaseModel):
    question_id: uuid.UUID
    ordinal: int
    total: int
    prompt: str
    competency_id: str
    hints_used: int
    followups_used: int
    is_followup: bool
    followup_prompt: str | None
    remaining_minutes: int


class TranscriptSegmentInput(BaseModel):
    """FR-V2/V3: one finalised STT segment and where it sits on the timeline.

    ``confidence`` is what the recogniser reported, unmodified. Whether that
    counts as *low* is the server's call (FR-V4) -- a client that decided for
    itself could hide its own uncertainty.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    #: FR-V5: the transcript is the artifact of record. Whether it was typed or
    #: spoken, this string -- and only this string -- is what gets graded.
    transcript: str = Field(default="", max_length=20_000)
    input_mode: AnswerInputMode = AnswerInputMode.TYPED
    #: Empty for typed answers. Bounded because it is client-supplied.
    segments: list[TranscriptSegmentInput] = Field(default_factory=list, max_length=500)
    duration_ms: int | None = Field(default=None, ge=0)
    #: FR-S6: a skip is recorded as skipped, not as wrong.
    skipped: bool = False
    #: FR-S8: client-supplied, so a retried submit never double-records.
    idempotency_key: str = Field(min_length=8, max_length=120)


class AnswerResponse(BaseModel):
    answer_id: uuid.UUID
    accepted: bool
    #: True when this was a retry of an already-recorded submit.
    replayed: bool
    session_completed: bool
    next_turn: TurnResponse | None


class HintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    trigger: HintTrigger = HintTrigger.REQUESTED


class HintResponse(BaseModel):
    """FR-E4f: the candidate is told a hint is being offered. No silent penalty."""

    level: str
    text: str
    remaining: int
    #: Stated plainly so the trade-off is the candidate's to make.
    scoring_note: str = (
        "This hint reduces credit on the concept it points at -- not on your whole answer. "
        "Your report shows both your raw and hint-adjusted scores."
    )
