"""The candidate feedback report (§4.11) -- the #1 product priority (§1.3).

Written to teach, not to score. Every gap carries the concept's authored
``why_it_matters`` verbatim and the grader's plain-language improvement note,
so the candidate leaves with the *idea* rather than a word to memorise (FR-F2).

Both raw and hint-adjusted scores are always present (FR-F5): showing only the
adjusted number hides the penalty, showing only the raw one hides the help.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.domain.enums import EvaluationStatus, QuestionStatus, Verdict
from app.models.evaluation import ConceptAssessment, Evaluation
from app.models.interview import InterviewSession, SessionQuestion
from app.models.ops import UsageCost
from app.services.scoring import (
    CompetencyRollup,
    QuestionScore,
    ScoredConcept,
    recommendation_for,
    rollup_competency,
    score_question,
)


@dataclass(slots=True)
class ConceptLine:
    concept_id: str
    label: str
    weight: str
    verdict: str
    why_it_matters: str
    evidence_quote: str | None
    improvement_note: str | None
    hint_discounted: bool


@dataclass(slots=True)
class QuestionReport:
    question_id: uuid.UUID
    ordinal: int
    competency_id: str
    prompt: str
    transcript: str
    band: int | None
    raw_score: float | None
    hint_adjusted_score: float | None
    hints_used: int
    status: str
    covered: list[ConceptLine] = field(default_factory=list)
    partial: list[ConceptLine] = field(default_factory=list)
    missed: list[ConceptLine] = field(default_factory=list)
    terminology_notes: list[str] = field(default_factory=list)
    #: FR-M-A4: derived by rule from link metadata, never a grader judgement.
    unsubstantiated_claim: bool = False


@dataclass(slots=True)
class SessionReport:
    session_id: uuid.UUID
    status: str
    mode: str
    seniority: str
    overall_raw: float
    overall_hint_adjusted: float
    recommendation: str
    graded_questions: int
    pending_questions: int
    competencies: list[dict[str, Any]] = field(default_factory=list)
    questions: list[QuestionReport] = field(default_factory=list)
    top_improvements: list[dict[str, str]] = field(default_factory=list)
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["session_id"] = str(self.session_id)
        for question in payload["questions"]:
            question["question_id"] = str(question["question_id"])
        return payload


def _latest_evaluation(question: SessionQuestion) -> Evaluation | None:
    """The most recent COMPLETE evaluation for this question.

    Evaluations are append-only, so "latest" is a read-time choice rather than
    a destructive one -- an older grade is still there to compare against when
    a rubric revision triggers a re-grade (§10 J4).
    """
    complete = [
        evaluation
        for evaluation in question.evaluations
        if evaluation.status == EvaluationStatus.COMPLETE
    ]
    return max(complete, key=lambda e: (e.rubric_version, e.created_at)) if complete else None


async def build_report(db: AsyncSession, session_id: uuid.UUID) -> SessionReport:
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(
            selectinload(InterviewSession.questions).selectinload(SessionQuestion.concepts),
            selectinload(InterviewSession.questions).selectinload(SessionQuestion.answers),
            selectinload(InterviewSession.questions).selectinload(SessionQuestion.hints),
            selectinload(InterviewSession.questions)
            .selectinload(SessionQuestion.evaluations)
            .selectinload(Evaluation.assessments),
        )
    )
    interview = (await db.execute(stmt)).scalars().unique().one_or_none()
    if interview is None:
        raise NotFoundError("Interview session not found.")

    reports: list[QuestionReport] = []
    per_competency: dict[str, list[QuestionScore]] = defaultdict(list)
    pending = 0

    for question in sorted(interview.questions, key=lambda q: q.ordinal):
        evaluation = _latest_evaluation(question)
        transcript = "\n\n".join(
            answer.transcript for answer in sorted(question.answers, key=lambda a: a.turn_index)
            if answer.transcript
        )
        report = QuestionReport(
            question_id=question.id,
            ordinal=question.ordinal,
            competency_id=question.competency_id,
            prompt=question.prompt,
            transcript=transcript,
            band=None,
            raw_score=None,
            hint_adjusted_score=None,
            hints_used=question.hint_count,
            status=question.status,
        )

        if evaluation is None:
            # G-008. "No evaluation" is three different situations, and calling
            # them all *pending* left the report page refreshing every four
            # seconds forever on a session that was already finished.
            #
            # A skipped question is deliberately never graded (FR-S6: a skip is
            # recorded as a skip, not as wrong), so it is complete, not late.
            # The same goes for a question that was never reached. Only a
            # question with an answer and no verdict is actually waiting on
            # something.
            if question.status != QuestionStatus.SKIPPED and transcript:
                pending += 1
            reports.append(report)
            continue

        by_concept = {concept.concept_id: concept for concept in question.concepts}
        assessments: list[ConceptAssessment] = list(evaluation.assessments)
        scored = [
            ScoredConcept(
                concept_id=assessment.concept_id,
                weight=by_concept[assessment.concept_id].weight,
                verdict=assessment.verdict,
                hint_discounted=assessment.hint_discounted,
            )
            for assessment in assessments
            if assessment.concept_id in by_concept
        ]
        score = score_question(scored)
        per_competency[question.competency_id].append(score)

        report.band = evaluation.band
        report.raw_score = evaluation.raw_score
        report.hint_adjusted_score = evaluation.hint_adjusted_score
        report.terminology_notes = list(evaluation.terminology_notes or [])
        # Derived by rule (FR-M-A4): this topic came from a resume item AND
        # every core concept went unmet. The grader never saw the claim; the
        # join happens here, afterwards, as a fact with its evidence attached.
        report.unsubstantiated_claim = bool(
            question.source_profile_item_id and score.all_core_missing
        )

        for assessment in sorted(assessments, key=lambda a: by_concept[a.concept_id].ordinal
                                 if a.concept_id in by_concept else 0):
            concept = by_concept.get(assessment.concept_id)
            if concept is None:
                continue
            line = ConceptLine(
                concept_id=concept.concept_id,
                label=concept.label,
                weight=concept.weight,
                verdict=assessment.verdict,
                why_it_matters=concept.why_it_matters,
                evidence_quote=assessment.evidence_quote,
                improvement_note=assessment.improvement_note,
                hint_discounted=assessment.hint_discounted,
            )
            if assessment.verdict == Verdict.COVERED:
                report.covered.append(line)
            elif assessment.verdict == Verdict.PARTIAL:
                report.partial.append(line)
            else:
                report.missed.append(line)

        reports.append(report)

    rollups: list[CompetencyRollup] = [
        rollup_competency(competency_id, scores)
        for competency_id, scores in sorted(per_competency.items())
    ]
    graded = sum(len(scores) for scores in per_competency.values())
    overall_raw = (
        sum(rollup.raw for rollup in rollups) / len(rollups) if rollups else 0.0
    )
    overall_adjusted = (
        sum(rollup.hint_adjusted for rollup in rollups) / len(rollups) if rollups else 0.0
    )

    cost = (
        await db.execute(
            select(func.coalesce(func.sum(UsageCost.usd), 0.0)).where(
                UsageCost.session_id == session_id
            )
        )
    ).scalar_one()

    return SessionReport(
        session_id=interview.id,
        status=interview.status,
        mode=interview.mode,
        seniority=interview.seniority,
        overall_raw=round(overall_raw, 4),
        overall_hint_adjusted=round(overall_adjusted, 4),
        recommendation=recommendation_for(overall_adjusted),
        graded_questions=graded,
        pending_questions=pending,
        competencies=[asdict(rollup) for rollup in rollups],
        questions=reports,
        top_improvements=_top_improvements(reports),
        cost_usd=round(float(cost), 6),
    )


def _top_improvements(reports: list[QuestionReport]) -> list[dict[str, str]]:
    """FR-F3: the three highest-leverage things to improve, and why each matters.

    Ranked by weight then by how badly it went, because a contradicted `core`
    concept is a wrong mental model -- the most valuable thing a candidate can
    find out, and the thing most likely to cost them a real interview.
    """
    rank = {"core": 0, "supporting": 1, "bonus": 2}
    severity = {Verdict.CONTRADICTED: 0, Verdict.MISSING: 1, Verdict.PARTIAL: 2}
    gaps = [
        (rank.get(line.weight, 3), severity.get(line.verdict, 3), report.competency_id, line)
        for report in reports
        for line in (*report.missed, *report.partial)
    ]
    gaps.sort(key=lambda row: (row[0], row[1], row[2]))
    return [
        {
            "competency_id": competency_id,
            "concept": line.label,
            "why_it_matters": line.why_it_matters,
            "what_to_add": line.improvement_note
            or "Explain the mechanism behind this in your own words.",
        }
        for _, _, competency_id, line in gaps[:3]
    ]


async def progress_series(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """FR-F4: competency scores over time, with the delta vs the previous session.

    A window function does the delta in the database rather than in Python --
    the query is the interesting part, and this is the read model the report
    page renders directly.
    """
    latest = (
        select(
            InterviewSession.id.label("session_id"),
            InterviewSession.completed_at.label("completed_at"),
            SessionQuestion.competency_id.label("competency_id"),
            Evaluation.hint_adjusted_score.label("score"),
        )
        .join(SessionQuestion, SessionQuestion.session_id == InterviewSession.id)
        .join(Evaluation, Evaluation.session_question_id == SessionQuestion.id)
        .where(
            InterviewSession.user_id == user_id,
            Evaluation.status == EvaluationStatus.COMPLETE,
            InterviewSession.completed_at.is_not(None),
        )
        .subquery()
    )

    averaged = (
        select(
            latest.c.session_id,
            latest.c.completed_at,
            latest.c.competency_id,
            func.avg(latest.c.score).label("score"),
        )
        .group_by(latest.c.session_id, latest.c.completed_at, latest.c.competency_id)
        .subquery()
    )

    windowed = select(
        averaged.c.session_id,
        averaged.c.completed_at,
        averaged.c.competency_id,
        averaged.c.score,
        func.lag(averaged.c.score)
        .over(partition_by=averaged.c.competency_id, order_by=averaged.c.completed_at)
        .label("previous_score"),
    ).order_by(averaged.c.completed_at)

    rows = (await db.execute(windowed)).all()
    return [
        {
            "session_id": str(row.session_id),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "competency_id": row.competency_id,
            "score": round(float(row.score), 4),
            "delta": (
                round(float(row.score) - float(row.previous_score), 4)
                if row.previous_score is not None
                else None
            ),
        }
        for row in rows
    ]
