"""Interview planning: selectors -> a persisted, reviewable plan (FR-P1).

Three properties worth stating up front, because they are what make the plan
more than a shuffle:

* **No LLM call happens here.** Questions and their standards come from the
  bank (IR-2), so producing a plan costs nothing and is instant (NFR-C3). The
  only variable costs in the whole product are STT and one grading call per
  answer.
* **The rubric is copied, not referenced.** A bank edit tomorrow cannot move
  the bar a candidate was measured against today (FR-E1a).
* **Framing is cosmetic.** Resume-derived wording may wrap a question; the
  standard behind it is identical for every candidate at that
  ``(competency, seniority)`` (FR-M0b). If sanitisation rejects the framing,
  the neutral wording is used and the interview proceeds (FR-M0d).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.domain.enums import (
    FitLevel,
    InterviewMode,
    QuestionStatus,
    Seniority,
    SessionPurpose,
)
from app.models.content import BankQuestion, Competency
from app.models.documents import JDRequirement, ProfileItem
from app.models.interview import (
    FitMapEntry,
    InterviewSession,
    ReductionResult,
    RubricConcept,
    SessionQuestion,
)
from app.services import question_gen
from app.services.plan_synthesis import SynthesisedPlan
from app.services.reduction import Selectors
from app.services.sanitize import sanitise_framing

logger = get_logger(__name__)

#: Ceiling per §5's intent: a technical practice session stays technical.
BEHAVIOURAL_SHARE = 0.2  # FR-B1c

#: How many questions a session of a given length should aim for.
#:
#: This replaces packing by each question's ``expected_minutes``, which looked
#: principled and behaved badly: those estimates sit at 5-7 minutes, so a
#: 10-minute session got two questions and a 45-minute one got seven -- barely
#: more, because the estimates dominated rather than the budget. Duration is a
#: choice the candidate makes about *how much practice they want*, so it should
#: move the count directly.
#:
#: Anchors are interpolated, so a value between them lands between them, and
#: anything past the last anchor holds at its count rather than extrapolating
#: into an interview nobody wants.
QUESTIONS_BY_MINUTES: tuple[tuple[int, int], ...] = (
    (10, 6),
    (20, 10),
    (30, 14),
    (45, 20),
)


def target_question_count(minutes: int) -> int:
    """Questions to aim for at this duration. Monotonic, and never zero."""
    anchors = QUESTIONS_BY_MINUTES
    if minutes <= anchors[0][0]:
        # Still scale below the first anchor rather than clamping: a 5-minute
        # session should be shorter than a 10-minute one, not equal to it.
        return max(1, round(minutes * anchors[0][1] / anchors[0][0]))
    for (low_min, low_count), (high_min, high_count) in pairwise(anchors):
        if minutes <= high_min:
            span = high_min - low_min
            return round(low_count + (minutes - low_min) * (high_count - low_count) / span)
    return anchors[-1][1]


#: Framing should sound like an interviewer, not like a quotation. Past this
#: many words we fall back to the neutral wording rather than reading a whole
#: resume bullet back at the candidate (FR-M0d).
FRAMING_SUBJECT_MAX_WORDS = 8

#: Where a resume bullet's useful phrase ends: a dash-delimited clause (hyphen,
#: en dash or em dash) or a comma following a word. The dash characters are
#: written as escapes so they can't be mistaken for a plain hyphen on review.
_DASHES = "-\u2013\u2014"  # hyphen, en dash, em dash
CLAUSE_BOUNDARY = re.compile(rf"\s+[{_DASHES}]\s+|(?<=[a-z]),\s+")


@dataclass(frozen=True, slots=True)
class PlannedSlot:
    ordinal: int
    competency_id: str
    bank_question: BankQuestion
    #: The complete text the candidate hears, already sanitised, or ``None`` to
    #: fall back to the bank's neutral wording.
    #:
    #: "Complete" is load-bearing. The bank path builds this by prepending a
    #: template prefix to the neutral wording; the synthesis path receives a
    #: whole question written from the candidate's documents. Resolving that
    #: difference here rather than at the row keeps one rule downstream:
    #: whatever is in this field is what gets said.
    asked_text: str | None
    source_profile_item_id: uuid.UUID | None


async def _load_bank(
    session: AsyncSession, competency_ids: Sequence[str], seniority: Seniority
) -> dict[str, BankQuestion]:
    """Resolve one active question per competency at this seniority.

    Rubrics are keyed by ``(competency_id, seniority)`` -- the same competency
    at a different level is a *different rubric*, not merely a harder question
    (Appendix C.2). If a level has no authored rubric we skip the competency
    rather than silently grading against the wrong bar.
    """
    if not competency_ids:
        return {}
    stmt = (
        select(BankQuestion)
        .where(
            BankQuestion.competency_id.in_(list(competency_ids)),
            BankQuestion.seniority == seniority.value,
            BankQuestion.active.is_(True),
        )
        # ⚠ Eager-loading `concepts` is correctness, not tuning. `build_plan`
        # copies the rubric after an await, and a lazily-loaded relationship
        # there raises MissingGreenlet at runtime -- on this code path only
        # (Appendix D.4).
        .options(selectinload(BankQuestion.concepts))
        .order_by(BankQuestion.competency_id, BankQuestion.rubric_version.desc())
    )
    result = await session.execute(stmt)
    best: dict[str, BankQuestion] = {}
    for question in result.scalars().unique():
        best.setdefault(question.competency_id, question)  # highest version wins
    return best


async def _top_up(
    db: AsyncSession,
    *,
    seniority: Seniority,
    already: Sequence[str],
    selected: Sequence[str],
    shortfall: int,
) -> list[tuple[str, BankQuestion]]:
    """Find more competencies to reach the target, nearest neighbours first.

    Order of preference, and each step is a weaker claim than the one before:

    1. **Competencies the document named that the bank has no rubric for.** The
       document asked for these; only our coverage was missing. Generate them.
    2. **Other competencies in the same domains.** A weaker claim -- the
       document did not name these -- but a backend JD that mentions three
       topics is still a backend interview, and practising adjacent ground is
       the point of practice.

    Never anything outside the domains in play: a Postgres JD must not produce
    a React question just to hit a number. Running short is better than running
    irrelevant.
    """
    picked: list[tuple[str, BankQuestion]] = []
    seen = set(already)

    # Which domains are actually in play, taken from what reduction selected.
    domains = set(
        (
            await db.execute(
                select(Competency.domain).where(Competency.competency_id.in_(list(selected)))
            )
        ).scalars()
    )
    if not domains:
        return picked

    unmet = [cid for cid in selected if cid not in seen]
    neighbours = list(
        (
            await db.execute(
                select(Competency.competency_id)
                .where(Competency.domain.in_(domains))
                .order_by(Competency.competency_id)
            )
        ).scalars()
    )
    # Last resort: any competency the bank has actually authored, whatever its
    # domain. A vague JD or a sparse resume must not silently buy a shorter
    # interview -- the candidate chose 45 minutes of practice and should get it.
    # Ranked last because it is the weakest claim to relevance, and only ever
    # reached once the two better sources are exhausted.
    fallback = list(
        (
            await db.execute(
                select(BankQuestion.competency_id)
                .where(
                    BankQuestion.seniority == seniority.value,
                    BankQuestion.active.is_(True),
                    BankQuestion.generated.is_(False),
                )
                .order_by(BankQuestion.competency_id)
            )
        ).scalars()
    )

    # Pass one: anything already in the bank, including rubrics generated for
    # an earlier session. Free, instant, and usually most of the shortfall once
    # the app has been used a few times.
    to_generate: list[str] = []
    for competency_id in [*unmet, *neighbours, *fallback]:
        if len(picked) >= shortfall:
            break
        if competency_id in seen:
            continue
        seen.add(competency_id)
        question = await question_gen.load_generated(
            db, competency_id=competency_id, seniority=seniority
        )
        if question is not None:
            picked.append((competency_id, question))
        elif len(to_generate) < settings.max_generations_per_plan:
            to_generate.append(competency_id)

    # Pass two: generate what is still missing, **capped and concurrent**.
    #
    # The cap is a cost and latency control, and it is not optional. A
    # 45-minute session that matched three competencies is seventeen short, and
    # generating seventeen rubrics would be seventeen model calls in one
    # planning request -- roughly $0.30 and over a minute of the candidate
    # staring at a spinner, every time. Capped at a few, the bank fills in
    # across sessions instead: the next person on that topic pays nothing.
    #
    # Concurrent because they are independent, and sequential calls would make
    # even the cap feel slow.
    remaining = shortfall - len(picked)
    if remaining > 0 and to_generate:
        wanted_now = to_generate[:remaining]
        generated = await asyncio.gather(
            *(
                question_gen.generate_for(db, competency_id=cid, seniority=seniority)
                for cid in wanted_now
            )
        )
        picked.extend(
            (cid, question) for cid, question in zip(wanted_now, generated, strict=True)
            if question is not None
        )

    logger.info(
        "plan_topped_up",
        added=len(picked),
        shortfall=shortfall,
        generated=len(to_generate[: max(0, shortfall - len(picked) + len(to_generate))]),
        domains=sorted(domains),
    )
    return picked


def _framing_for(item: ProfileItem | None) -> str | None:
    """Build resume-flavoured framing deterministically, then sanitise it.

    Deliberately a template rather than a generated sentence: framing is
    cosmetic, so paying an LLM call per question to make it prettier would
    trade real money for no assessment value.
    """
    if item is None:
        return None
    payload = item.corrected_payload or item.payload or {}
    subject = payload.get("name") or payload.get("title") or payload.get("skill")
    if not subject:
        return None

    # Trim to a phrase. A resume bullet is a whole sentence, and quoting the
    # whole thing back reads like a machine rather than an interviewer.
    subject = str(subject).strip().rstrip(".,;:")
    # Split on a dash-delimited clause (hyphen, en dash or em dash) or on a
    # comma that follows a word -- both mark where the useful phrase ends.
    subject = CLAUSE_BOUNDARY.split(subject)[0]
    words = subject.split()
    if not words or len(words) > FRAMING_SUBJECT_MAX_WORDS:
        # Better to ask the neutral question than to open with a garbled quote.
        return None

    detail = payload.get("stack") or payload.get("org")
    lead = f"You mentioned {subject}"
    if detail:
        lead += f" ({detail})"
    return sanitise_framing(f"{lead} — with that in mind:")


def _pick_framing_item(
    competency_id: str, items: Sequence[ProfileItem]
) -> ProfileItem | None:
    """Match a resume item to a topic by slug-token overlap, favouring recency.

    Cheap and explainable: slugs are readable, so "this question was framed
    from that bullet" is a fact you can check by eye rather than a similarity
    score you have to trust.
    """
    terms = {part for part in competency_id.split("-") if len(part) > 2}
    best: tuple[int, int, ProfileItem] | None = None
    for item in items:
        haystack = f"{item.source_text} {item.payload}".lower()
        hits = sum(1 for term in terms if term in haystack)
        if hits == 0:
            continue
        candidate = (hits, item.prominence, item)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


async def build_plan(
    db: AsyncSession,
    *,
    interview: InterviewSession,
    selectors: Selectors,
    profile_items: Sequence[ProfileItem] = (),
    jd_requirements: Sequence[JDRequirement] = (),
    synthesised: SynthesisedPlan | None = None,
) -> list[SessionQuestion]:
    """Materialise the plan: reduction row, question slots, frozen rubrics, fit map.

    Everything is staged on the session; the unit-of-work seam commits.

    ``synthesised`` is a plan already written and validated by
    ``services/plan_synthesis``. It arrives as ``BankQuestion`` rows and
    sanitised strings, never as prose -- the documents were read on the far side
    of the trust boundary in ``api/v1/sessions.py`` and do not reach here.
    """
    if synthesised is not None:
        return await _build_from_synthesis(
            db,
            interview=interview,
            synthesised=synthesised,
            seniority=selectors.seniority,
            profile_items=profile_items,
            jd_requirements=jd_requirements,
        )

    bank = await _load_bank(db, selectors.competency_ids, selectors.seniority)
    if not bank:
        raise ValidationError(
            "No authored questions match this topic and level yet.",
            competencies=list(selectors.competency_ids),
            seniority=selectors.seniority.value,
        )

    db.add(
        ReductionResult(
            session_id=interview.id,
            competency_ids=list(selectors.competency_ids),
            seniority=selectors.seniority.value,
            domain=selectors.domain.value if selectors.domain else None,
            source=selectors.source.value,
            discarded_candidates=list(selectors.discarded),
            model_version=selectors.model_version,
        )
    )

    # How many questions this length of session should aim for. The real count
    # is often lower, and that is not a failure: it is bounded by how many
    # competencies the JD or resume actually named *and* the bank has authored
    # rubrics for. Padding to hit a number would mean asking about things the
    # role never mentioned, which is the one thing §1.2 forbids.
    wanted = target_question_count(interview.target_minutes)
    ordered = [
        (competency_id, bank[competency_id])
        for competency_id in selectors.competency_ids
        if competency_id in bank
    ]

    # Top up a thin plan (practice only). Reduction returns what the document
    # actually named, and a resume names far less than a job description --
    # measured at 5.2 competencies against 7.1 -- so a 45-minute resume-mode
    # session was planning three questions. The duration is a promise about how
    # much practice you get; keeping it means finding more topics.
    #
    # Practice only, deliberately: official mode has to stay comparable between
    # candidates (FR-P4), and topics that appear because *this* document was
    # thin are not comparable.
    if len(ordered) < wanted and interview.purpose == SessionPurpose.PRACTICE:
        ordered.extend(
            await _top_up(
                db,
                seniority=Seniority(interview.seniority),
                already=[competency_id for competency_id, _ in ordered],
                selected=selectors.competency_ids,
                shortfall=wanted - len(ordered),
            )
        )

    slots: list[PlannedSlot] = []
    for competency_id, question in ordered:
        if len(slots) >= wanted:
            break
        item = (
            _pick_framing_item(competency_id, profile_items)
            if interview.mode in (InterviewMode.RESUME, InterviewMode.COMBINED)
            else None
        )
        framing = _framing_for(item)
        slots.append(
            PlannedSlot(
                ordinal=len(slots),
                competency_id=competency_id,
                bank_question=question,
                # A space, not a bare concatenation -- sanitisation strips
                # trailing whitespace, so joining without one runs the two
                # sentences together.
                asked_text=f"{framing} {question.neutral_wording}" if framing else None,
                source_profile_item_id=item.id if item else None,
            )
        )

    questions: list[SessionQuestion] = []
    for slot in slots:
        bank_question = slot.bank_question
        prompt = slot.asked_text
        session_question = SessionQuestion(
            session_id=interview.id,
            ordinal=slot.ordinal,
            competency_id=slot.competency_id,
            seniority=selectors.seniority.value,
            bank_question_id=bank_question.id,
            rubric_version=bank_question.rubric_version,
            rubric_family=bank_question.rubric_family,
            neutral_wording=bank_question.neutral_wording,
            reframe_wording=bank_question.reframe_wording,
            framing_text=prompt,
            source_profile_item_id=slot.source_profile_item_id,
            status=QuestionStatus.PENDING,
        )
        # Freeze the rubric onto the question (FR-P5).
        session_question.concepts = [
            RubricConcept(
                concept_id=concept.concept_id,
                ordinal=concept.ordinal,
                label=concept.label,
                weight=concept.weight,
                why_it_matters=concept.why_it_matters,
                signpost=concept.signpost,
                acceptable_signals=list(concept.acceptable_signals),
                common_misconceptions=list(concept.common_misconceptions),
            )
            for concept in bank_question.concepts
        ]
        db.add(session_question)
        questions.append(session_question)

    if interview.mode is InterviewMode.COMBINED and jd_requirements:
        _build_fit_map(db, interview, jd_requirements, profile_items)

    # Flush so the caller can serialise real ids. Flush is not commit -- the
    # seam still owns the transaction (Appendix D.1 #1); without this the
    # response would carry `id: null` for every question.
    await db.flush()

    logger.info(
        "plan_built",
        session_id=str(interview.id),
        questions=len(questions),
        mode=interview.mode,
        seniority=selectors.seniority.value,
    )
    return questions


async def _build_from_synthesis(
    db: AsyncSession,
    *,
    interview: InterviewSession,
    synthesised: SynthesisedPlan,
    seniority: Seniority,
    profile_items: Sequence[ProfileItem],
    jd_requirements: Sequence[JDRequirement],
) -> list[SessionQuestion]:
    """Materialise a plan that a model wrote, rather than one the bank held.

    Structurally identical to the bank path -- same rows, same frozen rubric,
    same fit map -- because everything downstream of here must not be able to
    tell the difference. The rubric was validated by the same
    ``validate_question`` the authored banks pass, and the question text was
    already sanitised, so what arrives here is the same kind of object either
    way.
    """
    db.add(
        ReductionResult(
            session_id=interview.id,
            competency_ids=[q.question.competency_id for q in synthesised.questions],
            seniority=seniority.value,
            # A free-form professional field, not a `Domain` member. The
            # taxonomy stopped being closed here; the column is a string and
            # always was.
            domain=synthesised.domain,
            source=interview.mode,
            discarded_candidates=[],
            model_version="synthesis",
        )
    )

    questions: list[SessionQuestion] = []
    for ordinal, planned in enumerate(synthesised.questions):
        bank_question = planned.question
        session_question = SessionQuestion(
            session_id=interview.id,
            ordinal=ordinal,
            competency_id=bank_question.competency_id,
            seniority=seniority.value,
            bank_question_id=bank_question.id,
            rubric_version=bank_question.rubric_version,
            rubric_family=bank_question.rubric_family,
            neutral_wording=bank_question.neutral_wording,
            reframe_wording=bank_question.reframe_wording,
            # Sanitised on the way out of synthesis. Null when it was rejected,
            # which falls back to the neutral wording -- a worse-worded
            # question, never a worse-scored one.
            framing_text=planned.asked_prompt,
            source_profile_item_id=None,
            status=QuestionStatus.PENDING,
            # Frozen, like the rubric below it.
            followups=list(bank_question.followups or []),
        )
        session_question.concepts = [
            RubricConcept(
                concept_id=concept.concept_id,
                ordinal=concept.ordinal,
                label=concept.label,
                weight=concept.weight,
                why_it_matters=concept.why_it_matters,
                signpost=concept.signpost,
                acceptable_signals=list(concept.acceptable_signals),
                common_misconceptions=list(concept.common_misconceptions),
            )
            for concept in bank_question.concepts
        ]
        db.add(session_question)
        questions.append(session_question)

    if interview.mode is InterviewMode.COMBINED and jd_requirements:
        _build_fit_map(db, interview, jd_requirements, profile_items)

    await db.flush()
    logger.info(
        "plan_built",
        session_id=str(interview.id),
        questions=len(questions),
        mode=interview.mode,
        seniority=seniority.value,
        source="synthesis",
        domain=synthesised.domain,
    )
    return questions


def _build_fit_map(
    db: AsyncSession,
    interview: InterviewSession,
    jd_requirements: Sequence[JDRequirement],
    profile_items: Sequence[ProfileItem],
) -> None:
    """FR-M-C1..C3.

    ``absent`` is not a deficit to punish. It selects an assess-learnability
    question -- reasoning from first principles and honest self-assessment --
    because the point is to find out whether someone can get there (FR-M-C4).
    """
    for requirement in jd_requirements:
        terms = {part for part in requirement.competency_id.split("-") if len(part) > 2}
        evidence = [
            item
            for item in profile_items
            if any(term in f"{item.source_text}".lower() for term in terms)
        ]
        strength = sum(item.prominence for item in evidence)
        if len(evidence) >= 2 or strength >= 3:
            fit = FitLevel.STRONG
        elif evidence:
            fit = FitLevel.PARTIAL
        else:
            fit = FitLevel.ABSENT
        db.add(
            FitMapEntry(
                session_id=interview.id,
                competency_id=requirement.competency_id,
                fit=fit.value,
                jd_weight=requirement.weight,
                evidence_item_ids=[str(item.id) for item in evidence[:5]],
            )
        )
