"""Interview session routes (§4.4, §4.6).

The turn loop lives here. Two things worth noticing in the code below:

* Every mutating call runs inside ``drain_guard.track()``, so a SIGTERM during
  a deploy waits for the turn to finish instead of severing it (NFR-S3).
* Answer submission is idempotent twice over -- a Redis claim for the fast
  retry, a unique constraint for the truth (FR-S8).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import Answerer, DbSession, SessionStarter
from app.authz.perms import Perm
from app.authz.policy import authorize_owned
from app.core import idempotency
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.pagination import apply_keyset, clamp_limit, finish_page
from app.core.shutdown import drain_guard
from app.domain.enums import DocumentStatus, InterviewMode, SessionStatus
from app.domain.state_machine import assert_transition
from app.models.documents import (
    JDProfile,
    JDVersion,
    JobDescription,
    ProfileItem,
    Resume,
    ResumeProfile,
    ResumeVersion,
)
from app.models.identity import Consent
from app.models.interview import InterviewSession
from app.models.ops import AuditLog
from app.schemas.interview import (
    AnswerRequest,
    AnswerResponse,
    ConsentRequest,
    CreateSessionRequest,
    HintRequest,
    HintResponse,
    PlannedQuestionResponse,
    SessionPlanResponse,
    SessionResponse,
    TurnResponse,
)
from app.services import interview as interview_service
from app.services import planning
from app.services.reduction import reduce_to_selectors
from app.services.spend import assert_within_cap

router = APIRouter(prefix="/sessions", tags=["interview"])
logger = get_logger(__name__)

#: G-014: parse outcomes that must never feed the trust boundary. `failed` is
#: included because an unparseable document yields no usable profile anyway,
#: and a clear refusal beats an empty interview nobody can explain.
_UNUSABLE_DOCUMENT_STATUSES = frozenset({DocumentStatus.QUARANTINED, DocumentStatus.FAILED})


def _session_response(
    interview: InterviewSession, question_count: int | None = None
) -> SessionResponse:
    """Serialise a session.

    ⚠ ``question_count`` is a parameter rather than ``len(interview.questions)``
    because this is also called on a freshly-created session whose ``questions``
    collection has never been loaded. Touching it there triggers lazy IO after
    the await boundary -- ``MissingGreenlet``, at runtime, on that path only
    (Appendix D.4).
    """
    return SessionResponse(
        id=interview.id,
        status=interview.status,
        mode=interview.mode,
        purpose=interview.purpose,
        seniority=interview.seniority,
        target_minutes=interview.target_minutes,
        question_count=(
            question_count if question_count is not None else len(interview.questions)
        ),
        created_at=interview.created_at,
        completed_at=interview.completed_at,
    )


def _turn_response(turn: interview_service.TurnView) -> TurnResponse:
    return TurnResponse(**asdict(turn))


async def _readable_session(
    db: DbSession, session_id: uuid.UUID, principal, *, with_rubric: bool = False
) -> InterviewSession:
    """A session this principal may **look at**.

    Includes the org escape hatch: a reviewer is meant to read a candidate's
    session. Use this for reads and nothing else.
    """
    interview = await interview_service.load_session(db, session_id, with_rubric=with_rubric)
    authorize_owned(
        principal,
        owner_user_id=interview.user_id,
        organization_id=interview.organization_id,
        org_perm=Perm.SESSION_READ_ORG,
    )
    return interview


async def _own_session(
    db: DbSession, session_id: uuid.UUID, principal, *, with_rubric: bool = False
) -> InterviewSession:
    """A session this principal may **act in** -- their own, and only theirs.

    G-002. Every mutation used to share the read helper, which grants
    ``SESSION_READ_ORG``. That meant a reviewer in the same organisation could
    consent on a candidate's behalf, start or abandon their interview, submit
    answers as them, and spend their hints. ``Answerer`` did not stop it,
    because reviewer and admin roles inherit member capabilities.

    Reading someone's interview and *taking* it are different acts, so they get
    different helpers. There is deliberately no org override here: if an
    administrative reason to mutate another person's session ever appears, it
    needs its own named capability and its own audit trail, not a reused one.
    """
    interview = await interview_service.load_session(db, session_id, with_rubric=with_rubric)
    if interview.user_id != principal.user_id:
        # The same shape as a missing session: whether someone else's session
        # exists is not this caller's business.
        raise NotFoundError("Interview session not found.")
    return interview


@router.post("", response_model=SessionPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest, principal: SessionStarter, db: DbSession
) -> SessionPlanResponse:
    """Create a session and generate its plan (FR-P1).

    The whole trust boundary happens inside this handler and nowhere else:
    document prose is loaded, reduced to selectors, and dropped. The
    ``InterviewSession`` rows written afterwards contain enums and links only.
    """
    if not drain_guard.accepting_new_work():
        # Draining for a deploy: refuse to *start* a session rather than begin
        # one we know we cannot finish (NFR-S3).
        raise ConflictError("The service is restarting. Please try again in a moment.")

    await assert_within_cap(db, principal.user_id)

    resume_text: str | None = None
    profile_items: list[ProfileItem] = []
    if payload.resume_version_id:
        version = await db.get(ResumeVersion, payload.resume_version_id)
        if version is None:
            raise NotFoundError("Resume version not found.")
        # G-001. The id came from the caller, so ownership has to be checked
        # here -- otherwise anyone holding a UUID can build an interview from
        # someone else's resume. The grader never sees the prose (§1.2), but
        # the framing quotes it back and the chosen competencies describe the
        # person, so this discloses plenty on its own.
        resume = await db.get(Resume, version.resume_id)
        if resume is None or resume.user_id != principal.user_id:
            # Deliberately the same 404 as "no such version": a distinct 403
            # confirms the id exists, which is the disclosure being prevented.
            raise NotFoundError("Resume version not found.")
        # G-014. A document held back for looking like an instruction rather
        # than a description must not become an interview. Reduction is
        # hardened against injection, but the first control is not feeding it
        # something we already decided we do not trust.
        if version.status in _UNUSABLE_DOCUMENT_STATUSES:
            raise ConflictError(
                "That resume was quarantined during parsing and cannot be used. "
                "Upload it again, or start from a job description instead."
            )
        profile = (
            await db.execute(
                select(ResumeProfile)
                .where(ResumeProfile.resume_version_id == version.id)
                .options(selectinload(ResumeProfile.items))
            )
        ).scalars().one_or_none()
        if profile is None:
            raise ConflictError("That resume is still being parsed.")
        profile_items = list(profile.items)
        # Prose, gathered here and here only. It reaches `reduce_to_selectors`
        # and is never persisted onto anything the grader can see.
        resume_text = "\n".join(item.source_text for item in profile_items)

    jd_text: str | None = None
    jd_requirements = []
    if payload.jd_version_id:
        jd_version = await db.get(JDVersion, payload.jd_version_id)
        if jd_version is None:
            raise NotFoundError("Job description not found.")
        # G-001, the JD half. A JD is org-scoped rather than personal -- a team
        # is meant to share one -- so the boundary is the organisation, not the
        # individual. Another org's JD is still none of our business.
        job_description = await db.get(JobDescription, jd_version.job_description_id)
        if job_description is None or (
            job_description.organization_id != principal.organization_id
        ):
            raise NotFoundError("Job description not found.")
        if jd_version.status in _UNUSABLE_DOCUMENT_STATUSES:
            raise ConflictError(
                "That job description was quarantined during parsing and cannot be used."
            )
        jd_text = jd_version.raw_text
        jd_profile = (
            await db.execute(
                select(JDProfile)
                .where(JDProfile.jd_version_id == jd_version.id)
                .options(selectinload(JDProfile.requirements))
            )
        ).scalars().one_or_none()
        jd_requirements = list(jd_profile.requirements) if jd_profile else []

    if payload.mode is InterviewMode.RESUME and resume_text is None:
        raise ValidationError("Resume-only mode needs a parsed resume version.")
    if payload.mode is InterviewMode.JD and jd_text is None:
        raise ValidationError("JD-only mode needs a job description.")
    if payload.mode is InterviewMode.COMBINED and not (resume_text and jd_text):
        raise ValidationError("Combined mode needs both a resume and a job description.")

    interview = InterviewSession(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        mode=payload.mode.value,
        purpose=payload.purpose.value,
        status=SessionStatus.CREATED,
        target_minutes=payload.target_minutes,
        seniority=payload.seniority.value,
        domain=payload.domain.value if payload.domain else None,
        resume_version_id=payload.resume_version_id,
        jd_version_id=payload.jd_version_id,
        accommodation=payload.accommodation,
    )
    db.add(interview)
    await db.flush()

    # ═══ TRUST BOUNDARY ═══ prose in, enums out. Nothing below this line
    # receives `resume_text` or `jd_text`.
    selectors = await reduce_to_selectors(
        db,
        mode=payload.mode,
        seniority=payload.seniority,
        resume_text=resume_text,
        jd_text=jd_text,
        domain=payload.domain,
        user_id=principal.user_id,
    )
    questions = await planning.build_plan(
        db,
        interview=interview,
        selectors=selectors,
        profile_items=profile_items,
        jd_requirements=jd_requirements,
    )

    interview.status = assert_transition(interview.status, SessionStatus.PLANNED).value
    interview.status = assert_transition(interview.status, SessionStatus.CONSENT_PENDING).value
    # Deliberately *not* `interview.questions = questions`: assigning to an
    # unloaded relationship collection makes SQLAlchemy load the existing one
    # first, which is lazy IO on the async path. The rows are already linked by
    # `session_id`, so the assignment buys nothing and costs a 500.

    return SessionPlanResponse(
        session=_session_response(interview, question_count=len(questions)),
        questions=[
            PlannedQuestionResponse(
                id=question.id,
                ordinal=question.ordinal,
                competency_id=question.competency_id,
                prompt=question.prompt,
            )
            for question in questions
        ],
        competencies=list(selectors.competency_ids),
        discarded_candidates=list(selectors.discarded),
    )


@router.get("", response_model=dict)
async def list_sessions(
    principal: SessionStarter,
    db: DbSession,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Keyset-paginated history. Compound key ``(created_at, id)``."""
    limit = clamp_limit(limit)
    stmt = select(InterviewSession).where(InterviewSession.user_id == principal.user_id)
    stmt = apply_keyset(stmt, InterviewSession, cursor, limit).options(
        selectinload(InterviewSession.questions)
    )
    rows = list((await db.execute(stmt)).scalars().unique().all())
    page = finish_page(rows, limit)
    return {
        "items": [_session_response(item).model_dump(mode="json") for item in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/{session_id}", response_model=SessionPlanResponse)
async def get_session(
    session_id: uuid.UUID, principal: SessionStarter, db: DbSession
) -> SessionPlanResponse:
    interview = await _readable_session(db, session_id, principal, with_rubric=True)
    return SessionPlanResponse(
        session=_session_response(interview),
        questions=[
            PlannedQuestionResponse(
                id=question.id,
                ordinal=question.ordinal,
                competency_id=question.competency_id,
                prompt=question.prompt,
            )
            for question in sorted(interview.questions, key=lambda q: q.ordinal)
        ],
        competencies=sorted({question.competency_id for question in interview.questions}),
    )


@router.post("/{session_id}/consent", response_model=SessionResponse)
async def give_consent(
    session_id: uuid.UUID, payload: ConsentRequest, principal: SessionStarter, db: DbSession
) -> SessionResponse:
    """FR-S2: the hard gate. No consent -> no recording, no session."""
    interview = await _own_session(db, session_id, principal)
    if not payload.all_accepted():
        raise ValidationError(
            "All consent items must be accepted before an interview can begin."
        )
    db.add(
        Consent(
            user_id=principal.user_id,
            session_id=interview.id,
            consent_version=payload.consent_version,
            accepted_at=datetime.now(UTC),
            disclosures={
                "ai_conducts_and_assesses": True,
                "recording": (
                    "the transcript, whether you typed it or spoke it. This app stores "
                    "and uploads no audio and no video. Speaking uses your browser's own "
                    "speech recognition, and in some browsers -- Chrome and Edge among "
                    "them -- that sends your audio to the browser vendor for transcription. "
                    "Typing avoids that entirely and is scored identically."
                ),
                "scored": "conceptual correctness, depth, concrete grounding, structure",
                "not_scored": (
                    "accent, fluency, grammar, speaking speed, confidence, emotion, "
                    "or anything inferred from your face or voice"
                ),
                "who_can_view": "you; in official mode, the hiring org you applied to",
                "retention_days": 180,
                "deletion": (
                    "DELETE /sessions/{id} removes this session and everything derived "
                    "from it; DELETE /auth/me removes the account entirely. Both are "
                    "immediate and synchronous."
                ),
                "withdrawal": "you can delete this session and all derived data at any time",
            },
        )
    )
    interview.status = assert_transition(interview.status, SessionStatus.DEVICE_CHECK).value
    return _session_response(interview)


@router.post("/{session_id}/start", response_model=TurnResponse)
async def start_session(
    session_id: uuid.UUID, principal: Answerer, db: DbSession
) -> TurnResponse:
    interview = await _own_session(db, session_id, principal, with_rubric=True)
    async with drain_guard.track():
        turn = await interview_service.start(db, interview)
    return _turn_response(turn)


@router.get("/{session_id}/turn", response_model=TurnResponse)
async def current_turn(
    session_id: uuid.UUID, principal: Answerer, db: DbSession
) -> TurnResponse:
    """FR-S8 resumability: a refresh or a reconnect lands right back here."""
    interview = await _readable_session(db, session_id, principal, with_rubric=True)
    question = interview_service.current_question(interview)
    if question is None:
        raise ConflictError("This session has no remaining questions.")
    return _turn_response(interview_service.build_turn(interview, question))


@router.post("/{session_id}/answers", response_model=AnswerResponse)
async def submit_answer(
    session_id: uuid.UUID, payload: AnswerRequest, principal: Answerer, db: DbSession
) -> AnswerResponse:
    interview = await _own_session(db, session_id, principal, with_rubric=True)
    question = next(
        (q for q in interview.questions if q.id == payload.question_id), None
    )
    if question is None:
        raise NotFoundError("That question is not part of this session.")

    scope = f"answer:{session_id}"
    if not await idempotency.claim(scope, payload.idempotency_key):
        # A retry arrived while the first is still in flight, or already
        # finished. Either way the DB is the arbiter -- read it, don't guess.
        cached = await idempotency.fetch_result(scope, payload.idempotency_key)
        if cached:
            # Serve the original outcome, but say plainly that this was a
            # replay -- the client asked twice and deserves to know which
            # answer it is looking at.
            return AnswerResponse.model_validate({**cached, "replayed": True})

    async with drain_guard.track():
        result = await interview_service.submit_answer(
            db,
            interview=interview,
            question=question,
            transcript=payload.transcript,
            idempotency_key=payload.idempotency_key,
            input_mode=payload.input_mode,
            segments=[
                interview_service.SegmentInput(
                    text=segment.text,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    confidence=segment.confidence,
                )
                for segment in payload.segments
            ],
            duration_ms=payload.duration_ms,
            skipped=payload.skipped,
        )

    response = AnswerResponse(
        answer_id=result.answer.id,
        accepted=True,
        replayed=result.replayed,
        session_completed=result.session_completed,
        next_turn=_turn_response(result.next_turn) if result.next_turn else None,
    )
    await idempotency.store_result(scope, payload.idempotency_key, response.model_dump(mode="json"))
    return response


@router.post("/{session_id}/hints", response_model=HintResponse)
async def request_hint(
    session_id: uuid.UUID, payload: HintRequest, principal: Answerer, db: DbSession
) -> HintResponse:
    """§6.4: help with the concept, never with the term."""
    interview = await _own_session(db, session_id, principal, with_rubric=True)
    question = next((q for q in interview.questions if q.id == payload.question_id), None)
    if question is None:
        raise NotFoundError("That question is not part of this session.")

    hint = await interview_service.give_hint(
        db, interview=interview, question=question, trigger=payload.trigger
    )
    return HintResponse(level=hint.level.value, text=hint.text, remaining=hint.remaining)


@router.post("/{session_id}/abandon", response_model=SessionResponse)
async def abandon_session(
    session_id: uuid.UUID, principal: Answerer, db: DbSession
) -> SessionResponse:
    interview = await _own_session(db, session_id, principal)
    interview.status = assert_transition(interview.status, SessionStatus.ABANDONED).value
    return _session_response(interview)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: uuid.UUID, principal: Answerer, db: DbSession) -> None:
    """Delete one session and everything derived from it (FR-R9 / NFR-P).

    G-009: consent says "you can delete the session and everything derived from
    it at any time" and there was no way to do so. Asking someone to agree to a
    capability that does not exist is the part that matters -- the missing
    endpoint is just how it shows.

    ``_own_session`` and not the readable one: deleting is the most destructive
    act available, so a reviewer's org-wide read must not reach it.

    The row cascade removes questions, answers, transcript segments, hints and
    evaluations. ``UsageCost`` rows survive by design -- they hold no
    transcript and no identity, and they are the only record of what was spent.
    """
    interview = await _own_session(db, session_id, principal)
    db.add(
        AuditLog(
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
            action="session.deleted",
            resource_type="interview_session",
            resource_id=interview.id,
            detail={"status": interview.status},
        )
    )
    await db.delete(interview)
    logger.info("session_deleted", session_id=str(session_id), user_id=str(principal.user_id))
