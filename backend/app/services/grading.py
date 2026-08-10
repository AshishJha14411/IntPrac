"""Grading: rubric + transcript in, evidenced concept verdicts out.

Runs in a worker, never on the request path -- grading is explicitly off the
critical path (§8.1), so a slow model can make a report late but can never make
an interview stutter.

The guarantees this module implements:

* **IR-1 by construction.** The payload is built by
  ``build_grading_payload``, which whitelists three keys. This function never
  sees a resume, a JD, or a name, because it never loads one.
* **Idempotent per (answer, rubric_version, model_version, prompt_version)**
  (FR-E6e). At-least-once delivery plus a unique constraint equals
  exactly-once effect.
* **Malformed output is quarantined, never defaulted** (FR-E6a). A score we
  cannot evidence is worse than no score, so it goes to a human.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.domain.enums import CostKind, EvaluationStatus, SessionStatus, Verdict
from app.domain.state_machine import can_transition
from app.llm.client import PRICING, LLMClient, LLMUsage, get_grader_client
from app.llm.prompts.grading import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    RubricConceptView,
    build_grading_payload,
    render_user_message,
)
from app.llm.schemas import GRADING_JSON_SCHEMA, GradingOutput
from app.models.evaluation import ConceptAssessment, Evaluation
from app.models.interview import Answer, SessionQuestion
from app.models.ops import UsageCost
from app.services.scoring import ScoredConcept, score_question

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GradeOutcome:
    evaluation_id: uuid.UUID
    status: EvaluationStatus
    replayed: bool


def _load_question(db: Session, answer: Answer) -> SessionQuestion:
    stmt = (
        select(SessionQuestion)
        .where(SessionQuestion.id == answer.session_question_id)
        .options(
            selectinload(SessionQuestion.concepts),
            selectinload(SessionQuestion.answers),
            selectinload(SessionQuestion.hints),
        )
    )
    return db.execute(stmt).scalars().unique().one()


def _combined_transcript(question: SessionQuestion) -> str:
    """All turns for this question, in order.

    Follow-up prompts are included because the answer only makes sense with the
    thing it is answering. They are interviewer text, not candidate claims, so
    including them does not widen the grader's input beyond the question.
    """
    parts: list[str] = []
    for answer in sorted(question.answers, key=lambda a: a.turn_index):
        if not answer.transcript:
            continue
        if answer.prompt_text:
            parts.append(f"[Interviewer follow-up] {answer.prompt_text}")
        parts.append(answer.transcript)
    return "\n\n".join(parts)


def _existing_evaluation(
    db: Session, answer_id: uuid.UUID, rubric_version: int, model_version: str
) -> Evaluation | None:
    stmt = select(Evaluation).where(
        Evaluation.answer_id == answer_id,
        Evaluation.rubric_version == rubric_version,
        Evaluation.model_version == model_version,
        Evaluation.prompt_version == PROMPT_VERSION,
    )
    return db.execute(stmt).scalars().one_or_none()


def grade_answer(
    db: Session, *, answer_id: uuid.UUID, client: LLMClient | None = None
) -> GradeOutcome:
    answer = db.get(Answer, answer_id)
    if answer is None or not answer.transcript.strip():
        # A skipped question is recorded as skipped, not as wrong (FR-S6), so
        # there is nothing here to grade.
        raise LookupError(f"No gradable answer for {answer_id}")

    question = _load_question(db, answer)
    client = client or get_grader_client()
    model_version = getattr(client, "_model", "stub")

    existing = _existing_evaluation(db, answer.id, question.rubric_version, model_version)
    if existing is not None and existing.status == EvaluationStatus.COMPLETE:
        return GradeOutcome(existing.id, EvaluationStatus.COMPLETE, replayed=True)

    concepts = sorted(question.concepts, key=lambda c: c.ordinal)
    payload = build_grading_payload(
        # The bank wording, never `question.prompt` -- the resume-derived
        # framing is cosmetic and must not reach the grader (FR-M0c).
        neutral_wording=question.neutral_wording,
        concepts=[
            RubricConceptView(
                concept_id=concept.concept_id,
                label=concept.label,
                weight=concept.weight,
                acceptable_signals=concept.acceptable_signals,
                common_misconceptions=concept.common_misconceptions,
            )
            for concept in concepts
        ],
        transcript=_combined_transcript(question),
    )

    evaluation = existing or Evaluation(
        answer_id=answer.id,
        session_question_id=question.id,
        rubric_version=question.rubric_version,
        model_version=model_version,
        prompt_version=PROMPT_VERSION,
        status=EvaluationStatus.PENDING,
    )
    db.add(evaluation)

    expected_ids = {concept.concept_id for concept in concepts}
    try:
        result = asyncio.run(
            client.structured(
                system=SYSTEM_PROMPT,
                user=render_user_message(payload),
                schema=GRADING_JSON_SCHEMA,
                # 3000, not 6000: measured output averaged ~1,500 tokens, so
                # this is a real ceiling rather than a number nothing reaches.
                # Hitting it is treated as a failure and retried (see the
                # MAX_TOKENS branch in the client) rather than accepted as a
                # truncated score.
                max_tokens=3000,
                # `minimal`, and this is measured rather than assumed.
                # `scripts/grader_bench.py` grades the bank's own golden answers
                # -- which ship with the verdicts a correct grader must produce
                # -- across models and thinking levels. Over 18 goldens:
                #
                #   flash      high      96% agreement   $0.02147/grade
                #   flash      low       99%             $0.00621
                #   flash-lite low       96%             $0.00150
                #   flash-lite minimal   97%             $0.00155
                #
                # More thinking did not buy accuracy. It cannot: grading is
                # closed-book. The rubric names the concepts, the signals say
                # what counts as reaching one, and a JSON schema fixes the
                # shape -- so the reasoning being paid for was re-deriving what
                # the prompt already contained.
                effort="minimal",
            )
        )
        parsed = GradingOutput.model_validate(result.data)
        if not parsed.covers(expected_ids):
            raise ValueError(
                "grader returned a different concept set than the rubric defines"
            )
    except (PydanticValidationError, ValueError) as exc:
        # FR-E6a: quarantine for human review rather than silently defaulting.
        # A best-effort parse here would produce a number nobody can defend.
        evaluation.status = EvaluationStatus.QUARANTINED
        evaluation.quarantine_reason = str(exc)[:2000]
        logger.error(
            "grading_quarantined", answer_id=str(answer.id), reason=type(exc).__name__
        )
        return GradeOutcome(evaluation.id, EvaluationStatus.QUARANTINED, replayed=False)
    except Exception as exc:  # vendor/transport failure -- retryable, not a verdict
        logger.warning("grading_failed", answer_id=str(answer.id), error=str(exc))
        raise

    # Which concepts a hint touched -- the scope of the credit reduction (FR-E4e).
    hinted = {
        concept_id
        for hint in question.hints
        for concept_id in (hint.touched_concept_ids or [])
    }

    evaluation.assessments.clear()
    scored: list[ScoredConcept] = []
    by_id = {concept.concept_id: concept for concept in concepts}
    for verdict in parsed.concept_verdicts:
        concept = by_id[verdict.concept_id]
        discounted = verdict.concept_id in hinted and verdict.verdict is not Verdict.MISSING
        evaluation.assessments.append(
            ConceptAssessment(
                concept_id=verdict.concept_id,
                verdict=verdict.verdict.value,
                evidence_quote=verdict.evidence_quote,
                has_evidence=bool(verdict.evidence_quote),
                hint_discounted=discounted,
                improvement_note=verdict.improvement_note,
            )
        )
        scored.append(
            ScoredConcept(
                concept_id=verdict.concept_id,
                weight=concept.weight,
                verdict=verdict.verdict.value,
                hint_discounted=discounted,
            )
        )

    score = score_question(scored)
    evaluation.raw_score = score.raw
    evaluation.hint_adjusted_score = score.hint_adjusted
    evaluation.band = score.band
    evaluation.terminology_notes = list(parsed.terminology_notes)
    evaluation.status = EvaluationStatus.COMPLETE
    evaluation.graded_at = datetime.now(UTC)
    evaluation.raw_output = result.data

    _record_cost(db, question=question, result_usage=result.usage)

    logger.info(
        "answer_graded",
        answer_id=str(answer.id),
        band=score.band,
        raw=score.raw,
        hint_adjusted=score.hint_adjusted,
        covered=score.covered,
        missing=score.missing,
    )
    return GradeOutcome(evaluation.id, EvaluationStatus.COMPLETE, replayed=False)


def _record_cost(db: Session, *, question: SessionQuestion, result_usage: LLMUsage) -> None:
    """NFR-C1: a session whose cost is unknown is a bug.

    One row per cost kind, each carrying its own dollar share, so "what did
    this interview cost, and which line item was it?" is a single GROUP BY
    rather than an archaeology exercise.
    """
    interview = question.session
    rates = PRICING.get(result_usage.model, PRICING["default"])
    for kind, units, rate in (
        (CostKind.LLM_INPUT_TOKENS, result_usage.input_tokens, rates[0]),
        (CostKind.LLM_OUTPUT_TOKENS, result_usage.output_tokens, rates[1]),
    ):
        if not units:
            continue
        db.add(
            UsageCost(
                session_id=interview.id if interview else None,
                user_id=interview.user_id if interview else None,
                kind=kind.value,
                units=float(units),
                usd=round(units * rate / 1_000_000, 8),
                model=result_usage.model,
            )
        )


def publish_session(db: Session, *, session_id: uuid.UUID) -> str:
    """Flip a session to published once every answered question has a verdict.

    Takes a session rather than opening one, exactly like ``grade_answer``
    above. That is not only tidiness: the test harness pins each run to a
    private schema via ``connect_args`` on *its* engine, so anything that opens
    its own connection reads a different schema and sees an empty database.
    A function that cannot be handed a session cannot be integration-tested.
    """
    from app.models.evaluation import Evaluation
    from app.models.interview import Answer, InterviewSession, SessionQuestion

    interview = db.get(InterviewSession, session_id)
    if interview is None:
        return "missing"

    # Per question, not per turn. A follow-up is another turn on the same
    # question and grading reads the combined transcript, so one question
    # yields one evaluation however many turns it took. Counting turns
    # demanded an evaluation per turn, which no question with a follow-up could
    # ever satisfy: the session stuck at `completed` and the dashboard said
    # "Grading…" permanently.
    answered_questions = set(
        db.execute(
            select(SessionQuestion.id)
            .join(Answer, Answer.session_question_id == SessionQuestion.id)
            .where(SessionQuestion.session_id == interview.id, Answer.transcript != "")
        ).scalars()
    )
    graded_questions = set(
        db.execute(
            select(Evaluation.session_question_id).where(
                Evaluation.session_question_id.in_(answered_questions or {uuid.uuid4()}),
                Evaluation.status.in_([EvaluationStatus.COMPLETE, EvaluationStatus.QUARANTINED]),
            )
        ).scalars()
    )

    pending = answered_questions - graded_questions
    if pending:
        # A plain exception, never `Task.retry()`. In workerless mode (ADR 010)
        # there is no broker to hold a retry, and Celery answers `retry()` there
        # with `MaxRetriesExceededError: Can't retry ...` -- which is what
        # filled the outbox with dead `session.completed` events. Failing
        # normally leaves the row pending and the outbox ledger is the retry.
        # Under a broker, `autoretry_for=(Exception,)` still applies.
        raise RuntimeError(f"{len(pending)} question(s) still awaiting a verdict")

    if can_transition(interview.status, SessionStatus.GRADED):
        interview.status = SessionStatus.GRADED
        interview.graded_at = datetime.now(UTC)
        # Practice mode shows the report immediately (FR-F1); official mode is
        # gated on the org's visibility policy (FR-F6), enforced on read.
        interview.published_at = datetime.now(UTC)
        interview.status = SessionStatus.PUBLISHED
        logger.info(
            "session_graded", session_id=str(session_id), questions=len(answered_questions)
        )
    return interview.status
