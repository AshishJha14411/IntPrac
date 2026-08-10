"""Read-only views of the content library.

Exposed so the taxonomy is browsable (and so a public demo page can show what
the bank actually contains) -- but the *rubrics themselves are not exposed to
candidates*. Handing over `acceptable_signals` before an interview would be
handing over the answer key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.content import BankQuestion, BankRubricConcept, Competency

router = APIRouter(prefix="/bank", tags=["bank"])


@router.get("/taxonomy")
async def taxonomy(db: DbSession, domain: str | None = Query(default=None)) -> dict[str, Any]:
    stmt = select(Competency).where(Competency.active.is_(True)).order_by(
        Competency.domain, Competency.competency_id
    )
    if domain:
        stmt = stmt.where(Competency.domain == domain)
    competencies = (await db.execute(stmt)).scalars().all()

    counts = dict(
        (
            await db.execute(
                select(BankQuestion.competency_id, func.count(BankQuestion.id))
                .where(BankQuestion.active.is_(True))
                .group_by(BankQuestion.competency_id)
            )
        ).all()
    )
    return {
        "competencies": [
            {
                "competency_id": competency.competency_id,
                "domain": competency.domain,
                "label": competency.label,
                "description": competency.description,
                "authored_questions": counts.get(competency.competency_id, 0),
            }
            for competency in competencies
        ]
    }


@router.get("/coverage")
async def coverage(db: DbSession) -> dict[str, Any]:
    """Bank health at a glance (FR-B2f).

    A competency with zero authored questions cannot be interviewed on, so
    "what's missing" is the most useful thing this endpoint can say.
    """
    rows = (
        await db.execute(
            select(
                BankQuestion.competency_id,
                BankQuestion.seniority,
                # ⚠ `distinct` matters: the outer join fans out one row per
                # concept, so a plain count reports the concept count as the
                # question count.
                func.count(func.distinct(BankQuestion.id)),
                func.count(func.distinct(BankRubricConcept.id)),
            )
            .outerjoin(BankRubricConcept, BankRubricConcept.question_id == BankQuestion.id)
            .where(BankQuestion.active.is_(True))
            .group_by(BankQuestion.competency_id, BankQuestion.seniority)
            .order_by(BankQuestion.competency_id, BankQuestion.seniority)
        )
    ).all()
    return {
        "entries": [
            {
                "competency_id": competency_id,
                "seniority": seniority,
                "questions": questions,
                "concepts": concepts,
            }
            for competency_id, seniority, questions, concepts in rows
        ],
        "total_questions": sum(row[2] for row in rows),
    }
