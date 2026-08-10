"""The live interview: turn loop, hints, follow-ups, resumability.

Two invariants this module is responsible for:

* **No completed answer is ever lost** (NFR-S2). The answer row is durably
  persisted before the turn advances, and submission is idempotent via a
  client-supplied key backed by a unique constraint (FR-S8). A retried submit
  after a dropped connection returns the original answer instead of creating a
  second one.
* **Hints help with concepts, never terms** (FR-E4b). Hint text is *authored
  content read from the frozen rubric*, not generated at runtime -- a model
  improvising a hint is precisely how the terminology the rubric is looking for
  would leak into the help.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.enums import (
    AnswerInputMode,
    CostKind,
    HintLevel,
    HintTrigger,
    QuestionStatus,
    SessionStatus,
)
from app.domain.state_machine import ANSWERABLE, assert_transition
from app.models.interview import (
    Answer,
    Hint,
    InterviewSession,
    RubricConcept,
    SessionQuestion,
    TranscriptSegment,
)
from app.models.ops import UsageCost
from app.services import coverage, outbox

logger = get_logger(__name__)

_HINT_LADDER = (HintLevel.L1_REFRAME, HintLevel.L2_SIGNPOST, HintLevel.L3_PARTIAL_REVEAL)

#: Below this, a first answer is thin enough to be worth one probe (FR-E5a).
SHALLOW_ANSWER_WORDS = 25


def _pending_followup(question: SessionQuestion) -> Answer | None:
    """A follow-up turn that has been asked but not yet answered."""
    return next(
        (
            answer
            for answer in question.answers
            if answer.turn_index > 0 and answer.prompt_text and not answer.transcript
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class TurnView:
    """What the client needs to render the current turn."""

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


async def load_session(
    db: AsyncSession, session_id: uuid.UUID, *, with_rubric: bool = False
) -> InterviewSession:
    """Eager-load everything the caller will touch.

    ⚠ No lazy IO in async (Appendix D.4): a relationship touched after the
    await boundary raises ``MissingGreenlet`` at runtime, on that code path
    only. Eager-loading here is not an optimisation, it is correctness.
    """
    loader = selectinload(InterviewSession.questions)
    options = [
        loader.selectinload(SessionQuestion.answers),
        loader.selectinload(SessionQuestion.hints),
    ]
    if with_rubric:
        options.append(loader.selectinload(SessionQuestion.concepts))
    stmt = select(InterviewSession).where(InterviewSession.id == session_id).options(*options)
    interview = (await db.execute(stmt)).scalars().unique().one_or_none()
    if interview is None:
        raise NotFoundError("Interview session not found.")
    return interview


def current_question(interview: InterviewSession) -> SessionQuestion | None:
    for question in interview.questions:
        if question.status in (QuestionStatus.PENDING, QuestionStatus.ASKED):
            return question
    return None


def build_turn(interview: InterviewSession, question: SessionQuestion) -> TurnView:
    answered = sum(1 for q in interview.questions if q.status == QuestionStatus.ANSWERED)
    pending_followup = _pending_followup(question)
    return TurnView(
        question_id=question.id,
        ordinal=question.ordinal,
        total=len(interview.questions),
        prompt=question.prompt,
        competency_id=question.competency_id,
        hints_used=question.hint_count,
        followups_used=question.followup_count,
        is_followup=pending_followup is not None,
        followup_prompt=pending_followup.prompt_text if pending_followup else None,
        # FR-S9: a visible remaining-time budget. Proportional rather than a
        # wall clock, so a candidate who thinks for a minute isn't punished by
        # a countdown that has nothing to do with what's left to ask.
        remaining_minutes=_remaining_minutes(interview, answered),
    )


def _remaining_minutes(interview: InterviewSession, answered: int) -> int:
    """An estimate of time left, and **only** an estimate (FR-S9).

    Nothing in this system ends a session because time ran out. This is
    practice: the plan is the promise, so every planned question gets asked
    however long it takes. ``target_minutes`` chooses *how many* questions to
    plan (``planning.target_question_count``) and then stops being a deadline.

    Two things follow, and both are deliberate:

    * It is proportional to questions left, not a wall clock, so thinking for a
      minute doesn't shrink it. A candidate who pauses is not being punished.
    * It accounts for follow-ups. A question that earns one takes roughly two
      turns, so pacing off ``target_minutes / questions`` alone told candidates
      a 30-minute session while asking 24 turns' worth — an estimate that
      confident and that wrong is worse than none.

    It can exceed ``target_minutes`` on a session that earns many follow-ups.
    That is the honest number, and the UI says it is an estimate.
    """
    total = len(interview.questions) or 1
    remaining = max(0, total - answered)
    # Turns actually taken so far, per question answered, floored at 1. Early
    # on there is nothing to measure, so assume one turn and let it correct
    # itself as the session reveals its own pace.
    turns_taken = sum(
        1 for question in interview.questions for a in question.answers if a.transcript
    )
    turns_per_question = max(1.0, turns_taken / answered) if answered else 1.0
    minutes_per_turn = interview.target_minutes / total
    return max(0, round(minutes_per_turn * remaining * turns_per_question))


async def start(db: AsyncSession, interview: InterviewSession) -> TurnView:
    """Move a consented, device-checked session into ``in_progress``.

    ⚠ This deliberately does **not** walk the ``consent_pending → device_check``
    edge for you. Only the consent endpoint may take that step, so a session
    that never recorded consent cannot reach ``in_progress`` at all -- the graph
    is the gate (FR-S2), rather than a check somewhere that could be skipped.
    """
    interview.status = assert_transition(interview.status, SessionStatus.IN_PROGRESS).value
    interview.started_at = interview.started_at or datetime.now(UTC)

    question = current_question(interview)
    if question is None:
        raise ValidationError("This session has no planned questions.")
    if question.status == QuestionStatus.PENDING:
        question.status = QuestionStatus.ASKED
        question.asked_at = datetime.now(UTC)
    return build_turn(interview, question)


def _require_answerable(interview: InterviewSession) -> None:
    if SessionStatus(interview.status) not in ANSWERABLE:
        raise ConflictError(
            f"This session is '{interview.status}' and is not accepting answers.",
            status=interview.status,
        )


def require_current_question(
    interview: InterviewSession, question: SessionQuestion
) -> None:
    """G-003: the server owns turn order, not the UI.

    Previously any question id belonging to the session was accepted, which let
    a direct caller answer a question that had not been asked yet, add turns to
    one already finished, or spend hints on a future question and mark its
    concepts hint-discounted before ever seeing them. None of that is reachable
    through the app, and "not reachable through our UI" is not a control.

    A stale browser tab hits this too, which is why it is a 409 with the
    current position rather than a bare rejection: the client can resynchronise
    from the error instead of guessing.
    """
    _require_answerable(interview)
    expected = current_question(interview)
    if expected is None:
        raise ConflictError("Every question in this session has been answered.")
    if expected.id != question.id:
        raise ConflictError(
            "That is not the question currently being asked. Reload to catch up.",
            expected_question_id=str(expected.id),
            expected_ordinal=expected.ordinal,
        )


def _replay_result(interview: InterviewSession, existing: Answer) -> SubmitResult:
    """Reconstruct the original outcome of a submit we already recorded.

    G-005. This used to return ``build_turn(interview, question)`` with
    ``session_completed=False`` hardcoded -- a *fabricated* response describing
    the question the caller happened to ask about, not what actually happened.
    Two ways that was wrong: replaying the last answer reported the session as
    still running, and replaying an older one pointed at the wrong turn.

    Redis holds the true original response for 24 hours and the route serves it
    when present (that path is untouched and still preferred). This is what
    happens after a Redis restart or a TTL expiry, and the answer is derived
    from the database rather than invented: the durable record is the arbiter,
    which is the same principle as the unique constraint one layer down.
    """
    resumable = current_question(interview)
    return SubmitResult(
        answer=existing,
        replayed=True,
        # Where the session actually is now, not where the replayed call was.
        next_turn=build_turn(interview, resumable) if resumable else None,
        session_completed=resumable is None,
    )


async def _find_by_idempotency_key(db: AsyncSession, key: str) -> Answer | None:
    return (
        await db.execute(select(Answer).where(Answer.idempotency_key == key))
    ).scalars().one_or_none()


@dataclass(frozen=True, slots=True)
class SubmitResult:
    answer: Answer
    replayed: bool
    next_turn: TurnView | None
    session_completed: bool


@dataclass(frozen=True, slots=True)
class SegmentInput:
    """One finalised STT segment, as the service layer sees it.

    A plain struct rather than the request schema, so nothing under
    ``services/`` has to know what the wire format looks like.
    """

    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


async def _write_segments(
    db: AsyncSession, answer: Answer, segments: Sequence[SegmentInput]
) -> None:
    """Replace this answer's transcript segments (FR-V2/V3/V4).

    Written with an explicit DELETE + ``db.add`` rather than by mutating
    ``answer.segments``: touching that relationship on an answer loaded from the
    database triggers lazy IO inside an async request, which is ``MissingGreenlet``
    in production and nowhere else (Appendix D.4). A re-submitted follow-up turn
    is exactly the case where the collection would be non-empty.
    """
    await db.execute(delete(TranscriptSegment).where(TranscriptSegment.answer_id == answer.id))
    threshold = settings.stt_low_confidence_threshold
    for ordinal, segment in enumerate(segments):
        db.add(
            TranscriptSegment(
                answer_id=answer.id,
                ordinal=ordinal,
                text=segment.text,
                # A recogniser that reports a backwards span is a bug in the
                # recogniser; clamp rather than store something unplottable.
                start_ms=segment.start_ms,
                end_ms=max(segment.end_ms, segment.start_ms),
                confidence=segment.confidence,
                low_confidence=(
                    segment.confidence is not None and segment.confidence < threshold
                ),
            )
        )


async def submit_answer(
    db: AsyncSession,
    *,
    interview: InterviewSession,
    question: SessionQuestion,
    transcript: str,
    idempotency_key: str,
    input_mode: AnswerInputMode = AnswerInputMode.TYPED,
    segments: Sequence[SegmentInput] | None = None,
    duration_ms: int | None = None,
    skipped: bool = False,
) -> SubmitResult:
    """Persist one turn, then decide whether to follow up or advance.

    Ordering is deliberate: the answer is written **before** anything decides
    what happens next, so a crash between the two loses a decision, never an
    answer.
    """
    # G-005: the replay check runs **first**, before any state validation.
    #
    # It used to run after `require_current_question`, which meant a retry of
    # the *final* answer -- the commonest place for a response to be lost, since
    # the session completes in the same request -- came back 409 "not the
    # current question" rather than the original success. Same for a retry that
    # arrived after the interview had moved on. A replay is a question about
    # something that already happened, so present state cannot make it invalid.
    existing = await _find_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        return _replay_result(interview, existing)

    require_current_question(interview, question)

    # A pending follow-up is an already-persisted turn awaiting its transcript,
    # so fill it in place rather than creating a second row for the same turn.
    pending = _pending_followup(question)
    if pending is not None:
        pending.transcript = transcript.strip()
        pending.input_mode = input_mode.value
        pending.idempotency_key = idempotency_key
        pending.duration_ms = duration_ms
        pending.skipped = skipped
        pending.submitted_at = datetime.now(UTC)
        answer = pending
    else:
        turn_index = len(question.answers)
        if turn_index > settings.max_followups_per_question:
            raise ConflictError("This question has already used all of its turns.")
        answer = Answer(
            session_question_id=question.id,
            turn_index=turn_index,
            prompt_text=None,
            transcript=transcript.strip(),
            input_mode=input_mode.value,
            idempotency_key=idempotency_key,
            duration_ms=duration_ms,
            skipped=skipped,
            submitted_at=datetime.now(UTC),
        )
        db.add(answer)

    try:
        await db.flush()
    except IntegrityError:
        # Two concurrent retries raced. Never pre-check for uniqueness --
        # catch the violation and return the winner (Appendix D.1 #2).
        await db.rollback()
        winner = await _find_by_idempotency_key(db, idempotency_key)
        if winner is None:
            raise
        return SubmitResult(winner, True, None, False)

    if pending is None:
        question.answers.append(answer)

    if segments:
        # After the flush above, so `answer.id` exists to hang them off.
        await _write_segments(db, answer, segments)
        # NFR-C1: a session whose cost is unknown is a bug -- and that has to
        # stay true when a cost happens to be zero. Recording the seconds with
        # `usd=0.0` says "we measured this and it was free", which is a
        # different claim from silence, and it means swapping to a metered STT
        # later changes a rate, not the accounting.
        if duration_ms:
            db.add(
                UsageCost(
                    session_id=interview.id,
                    user_id=interview.user_id,
                    kind=CostKind.STT_SECONDS,
                    units=round(duration_ms / 1000, 2),
                    usd=0.0,
                    vendor="browser",
                    model="web-speech-api",
                )
            )

    # FR-E5a: before moving on, decide whether this answer has earned one more
    # turn. Two triggers, and the order matters.
    #
    # 1. A core concept the answer never reached. This is the one that stops a
    #    report saying "missing" about something nobody asked. It used to need
    #    grading -- which is off the critical path (§8.1) and costs money -- but
    #    `coverage` approximates it with free lexical overlap, which is precise
    #    enough for a decision whose worst outcome is one extra question.
    # 2. A very thin answer, by word count. Kept as a backstop for the case
    #    where someone says almost nothing but happens to land a keyword.
    #
    # A follow-up you get two seconds late is worth more than a perfect one
    # after the interview has ended.
    if (
        not skipped
        and answer.turn_index == 0
        and question.followup_count < settings.max_followups_per_question
        and answer.transcript
    ):
        combined = " ".join(turn.transcript for turn in question.answers if turn.transcript)
        untouched = coverage.untouched_core_concepts(question.concepts, combined)
        thin = len(answer.transcript.split()) < SHALLOW_ANSWER_WORDS
        if untouched or thin:
            # Prefer the concept with the strongest authored signpost to point
            # at; falling back to a generic prompt when nothing was authored.
            target = next((concept for concept in untouched if concept.signpost), None)
            await add_followup(db, question=question, target=target)
            logger.info(
                "followup_triggered",
                question_id=str(question.id),
                reason="uncovered_core" if untouched else "short_answer",
                untouched=[concept.concept_id for concept in untouched],
            )
            return SubmitResult(
                answer=answer,
                replayed=False,
                next_turn=build_turn(interview, question),
                session_completed=False,
            )

    question.status = QuestionStatus.SKIPPED if skipped else QuestionStatus.ANSWERED

    # Grading is off the critical path (§8.1): stage an outbox event and move on.
    outbox.enqueue(
        db,
        aggregate_type="answer",
        aggregate_id=answer.id,
        event_type=outbox.EVENT_ANSWER_SUBMITTED,
        payload={"session_id": str(interview.id), "question_id": str(question.id)},
    )

    next_question = current_question(interview)
    completed = next_question is None
    if completed:
        interview.status = assert_transition(interview.status, SessionStatus.COMPLETED).value
        interview.completed_at = datetime.now(UTC)
        outbox.enqueue(
            db,
            aggregate_type="session",
            aggregate_id=interview.id,
            event_type=outbox.EVENT_SESSION_COMPLETED,
            payload={"session_id": str(interview.id)},
        )
    else:
        if next_question.status == QuestionStatus.PENDING:
            next_question.status = QuestionStatus.ASKED
            next_question.asked_at = datetime.now(UTC)
        interview.current_question_ordinal = next_question.ordinal

    logger.info(
        "answer_submitted",
        session_id=str(interview.id),
        question_ordinal=question.ordinal,
        turn_index=answer.turn_index,
        skipped=skipped,
        chars=len(answer.transcript),
    )
    return SubmitResult(
        answer=answer,
        replayed=False,
        next_turn=None if completed else build_turn(interview, next_question),
        session_completed=completed,
    )


# ---------------------------------------------------------------------------
# Hints (§6.4)
# ---------------------------------------------------------------------------
def _uncovered_core(concepts: Sequence[RubricConcept]) -> RubricConcept | None:
    """The first `core` concept a hint should point at.

    Ordered by the rubric's own ordinal, so the ladder walks the concepts in
    the order the author intended rather than an arbitrary one.
    """
    core = [concept for concept in concepts if concept.weight == "core"]
    for concept in sorted(core, key=lambda c: c.ordinal):
        if not concept.hint_touched:
            return concept
    return core[0] if core else None


@dataclass(frozen=True, slots=True)
class HintView:
    level: HintLevel
    text: str
    touched_concept_ids: list[str]
    remaining: int


async def give_hint(
    db: AsyncSession,
    *,
    interview: InterviewSession,
    question: SessionQuestion,
    trigger: HintTrigger = HintTrigger.REQUESTED,
) -> HintView:
    """Advance one rung of the hint ladder. Never past L3 (FR-E4a).

    Every rung's text comes from authored bank content copied onto this
    question. Nothing here composes a sentence from the rubric's
    ``acceptable_signals``, because those are the exact words the grader looks
    for -- handing them over would score the hint, not the candidate.
    """
    # G-003: hints were reachable before consent and after completion, on any
    # question in the session. A hint marks its concept discounted, so this was
    # a way to quietly lower the bar on a question not yet asked.
    require_current_question(interview, question)
    if question.hint_count >= len(_HINT_LADDER):
        raise ConflictError("No further hints are available for this question.")

    level = _HINT_LADDER[question.hint_count]
    concept = _uncovered_core(question.concepts)
    touched: list[str] = []

    if level is HintLevel.L1_REFRAME:
        # Same question, different words. Zero content added -- and if no
        # reframe was authored, we say so rather than inventing one.
        text = question.reframe_wording or (
            "Let me put that another way: " + question.neutral_wording
        )
    elif level is HintLevel.L2_SIGNPOST:
        if concept is None or not concept.signpost:
            raise ConflictError("No conceptual signpost is available for this question.")
        text = concept.signpost
        touched = [concept.concept_id]
    else:
        if concept is None:
            raise ConflictError("No core concept is available to reveal.")
        # L3 states one core concept plainly and asks the candidate to build on
        # it. This is the only rung that reveals content, which is why it is
        # last and why the credit discount applies to this concept alone.
        text = f"Here's one piece of it: {concept.label}. Can you build on that?"
        touched = [concept.concept_id]

    for rubric_concept in question.concepts:
        if rubric_concept.concept_id in touched:
            rubric_concept.hint_touched = True

    db.add(
        Hint(
            session_question_id=question.id,
            level=level.value,
            trigger=trigger.value,
            text=text,
            touched_concept_ids=touched,
        )
    )
    question.hint_count += 1
    logger.info(
        "hint_given",
        question_id=str(question.id),
        level=level.value,
        trigger=trigger.value,
        touched=touched,
    )
    return HintView(
        level=level,
        text=text,
        touched_concept_ids=touched,
        remaining=len(_HINT_LADDER) - question.hint_count,
    )


# ---------------------------------------------------------------------------
# Follow-ups (§6.5)
# ---------------------------------------------------------------------------
#: Neutral and never leading (FR-E5c). "Isn't it because of X?" would hand over
#: the answer; these ask for more of the candidate's own reasoning.
FOLLOWUP_TEMPLATES: tuple[str, ...] = (
    "Tell me more about how that behaves when it's under load.",
    "What would you check first if that didn't work the way you expected?",
)


def _authored_followup(
    question: SessionQuestion, target: RubricConcept | None
) -> str | None:
    """A written follow-up for the gap, if the plan came with one.

    Prefers one aimed at the concept the answer missed; falls back to any
    unused follow-up on the question. Returns ``None`` for authored bank
    questions, which have none and take the signpost path instead.

    Indexed by ``followup_count`` so the second follow-up is not the first one
    again -- asking the same thing twice reads as the interviewer not listening.
    """
    available = [
        item.get("prompt", "")
        for item in (question.followups or [])
        if isinstance(item, dict) and item.get("prompt")
    ]
    if not available:
        return None
    if target is not None:
        aimed = [
            item.get("prompt", "")
            for item in question.followups
            if isinstance(item, dict) and item.get("targets_concept_id") == target.concept_id
        ]
        if aimed:
            return aimed[question.followup_count % len(aimed)]
    return available[question.followup_count % len(available)]


async def add_followup(
    db: AsyncSession, *, question: SessionQuestion, target: RubricConcept | None = None
) -> str:
    """Ask one more thing inside the existing rubric (FR-E5b).

    A follow-up may not introduce a new competency -- doing so would break the
    comparability guarantee (FR-P4), because two candidates on the same posting
    would end up measured on different things.

    ``target`` is a core concept the answer never reached. Pointing at it costs
    something and that cost is recorded: the follow-up uses the concept's
    authored **signpost**, which is L2 hint content, so the concept is marked
    ``hint_touched`` and an audit row is written. Two deliberate choices in how
    that is done:

    * The candidate is **told** it is a nudge, in the prompt itself. FR-E4f
      forbids a silent penalty, and this help was not requested.
    * It does **not** consume a rung of the hint ladder. The ladder is the
      candidate's to spend; the interviewer noticing a gap should not quietly
      empty it. Only the per-concept credit discount applies.

    The alternative was to report the concept missing without ever asking,
    which is what this exists to stop.
    """
    if question.followup_count >= settings.max_followups_per_question:
        raise ConflictError("This question has already used both follow-ups.")

    authored = _authored_followup(question, target)
    if authored is not None:
        # A real interviewer's follow-up: it probes the gap without naming the
        # concept or its terminology, so it is **not** a hint and carries no
        # discount. That is the whole reason it is worth writing one.
        #
        # The signpost branch below exists because the authored banks have no
        # follow-ups, and pointing at a concept by describing it *is* help --
        # FR-E4f forbids charging for that silently, so it is disclosed and
        # discounted. Prefer this branch whenever a real follow-up exists.
        prompt = authored
    elif target is not None and target.signpost:
        prompt = (
            f"Before we move on, one nudge on the same question — {target.signpost} "
            "(Pointing you at this counts as a hint, so it is discounted in the "
            "hint-adjusted score. Your raw score is unaffected.)"
        )
        target.hint_touched = True
        db.add(
            Hint(
                session_question_id=question.id,
                level=HintLevel.L2_SIGNPOST.value,
                trigger=HintTrigger.UNCOVERED.value,
                text=target.signpost,
                touched_concept_ids=[target.concept_id],
            )
        )
    else:
        prompt = FOLLOWUP_TEMPLATES[question.followup_count % len(FOLLOWUP_TEMPLATES)]
    turn_index = len(question.answers)
    placeholder = Answer(
        session_question_id=question.id,
        turn_index=turn_index,
        prompt_text=prompt,
        transcript="",
        idempotency_key=f"followup-{question.id}-{turn_index}",
        submitted_at=datetime.now(UTC),
    )
    db.add(placeholder)
    question.answers.append(placeholder)
    question.followup_count += 1
    question.status = QuestionStatus.ASKED
    return prompt


async def count_sessions_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count(InterviewSession.id)).where(
                    InterviewSession.user_id == user_id
                )
            )
        ).scalar_one()
    )
