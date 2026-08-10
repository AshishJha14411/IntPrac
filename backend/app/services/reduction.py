"""═══════════════════════════════════════════════════════════════════════════
THE TRUST BOUNDARY (§1.2)
═══════════════════════════════════════════════════════════════════════════════

    resume text ─┐
                 ├─►  [ REDUCTION ]  ─►  {competency_ids[], seniority, domain}
    JD text ─────┘    (schema-validated,          ▲
                       closed taxonomy)           │
                                        ═════════╪═════════  TRUST BOUNDARY
                       free text is DISCARDED here; nothing past this
                       line ever receives resume or JD prose

This module is the *only* consumer of document prose in the entire system.
``reduce_to_selectors`` takes text and returns ``Selectors`` -- a frozen struct
of validated enum values with no free-text field on it. Every caller downstream
of here (planning, rubric resolution, grading, scoring, the report) takes
``Selectors``, so there is no code path through which prose can travel further,
and adding one would require changing this signature.

The consequence, stated as the requirement it satisfies (NFR-INJ1): the maximum
achievable impact of a hostile document is *the wrong topics were selected*.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import Domain, InterviewMode, Seniority
from app.llm.client import LLMClient, LLMResult, get_reducer_client
from app.llm.prompts import reduction as prompt
from app.llm.schemas import REDUCTION_JSON_SCHEMA, ReductionOutput
from app.models.content import BankQuestion, Competency
from app.services import usage
from app.services.sanitize import truncate_for_reduction

logger = get_logger(__name__)

MIN_COMPETENCIES = 3
MAX_COMPETENCIES = 20  # matches the top of planning.QUESTIONS_BY_MINUTES


@dataclass(frozen=True, slots=True)
class Selectors:
    """Everything downstream is allowed to know. Enums only, by construction."""

    competency_ids: tuple[str, ...]
    seniority: Seniority
    domain: Domain | None
    source: InterviewMode
    discarded: tuple[str, ...] = field(default=())
    model_version: str = "rules-v1"


async def _taxonomy(session: AsyncSession, domain: Domain | None) -> list[str]:
    """Competencies that actually have an active bank question.

    Offering a topic with no authored rubric would produce a question we cannot
    grade, so the "allowed" list is the *answerable* list, not the full
    taxonomy.
    """
    stmt = (
        select(Competency.competency_id)
        .join(BankQuestion, BankQuestion.competency_id == Competency.competency_id)
        .where(Competency.active.is_(True), BankQuestion.active.is_(True))
        .distinct()
    )
    if domain is not None:
        stmt = stmt.where(Competency.domain == domain.value)
    return sorted((await session.execute(stmt)).scalars().all())


async def reduce_to_selectors(
    session: AsyncSession,
    *,
    mode: InterviewMode,
    seniority: Seniority,
    resume_text: str | None,
    jd_text: str | None,
    domain: Domain | None = None,
    client: LLMClient | None = None,
    user_id: uuid.UUID | None = None,
) -> Selectors:
    """Turn untrusted prose into a validated selector set.

    ``seniority`` is a **parameter, not an inference**. It comes from the JD or
    the reviewer in official mode and from the candidate in practice mode
    (§12.5). Inferring it from the resume would let a document move the standard
    it is measured against, which is precisely the influence this boundary
    exists to remove.
    """
    allowed = await _taxonomy(session, domain)
    if not allowed:
        logger.warning("reduction_empty_taxonomy", domain=domain)
        return Selectors((), seniority, domain, mode, model_version="empty-bank")

    client = client or get_reducer_client()
    result: LLMResult = await client.structured(
        system=prompt.SYSTEM_PROMPT,
        user=prompt.render_user_message(
            allowed_competencies=allowed,
            resume_text=truncate_for_reduction(resume_text) if resume_text else None,
            jd_text=truncate_for_reduction(jd_text) if jd_text else None,
        ),
        schema=REDUCTION_JSON_SCHEMA,
        max_tokens=4000,
        # Reduction is classification against a closed list of ids, not prose.
        # Same finding as grading: the thinking was not buying accuracy.
        effort="low",
    )

    # NFR-C1. Reduction had never recorded its spend -- one model call per
    # session, invisible in our own totals since the day it was written, which
    # is exactly why they did not match the provider's dashboard.
    usage.record_async(session, result.usage, user_id=user_id)

    parsed = ReductionOutput.model_validate(result.data)

    # ── IR-4: validate against the closed taxonomy. Anything not in it is
    # dropped, which is what bounds the blast radius of a hostile document.
    allowed_set = set(allowed)
    kept: list[str] = []
    discarded: list[str] = []
    for candidate in sorted(parsed.competencies, key=lambda c: -c.confidence):
        if candidate.competency_id in allowed_set and candidate.competency_id not in kept:
            kept.append(candidate.competency_id)
        else:
            discarded.append(candidate.competency_id)

    if discarded:
        # Not an error -- a signal. A spike here means the bank has a gap
        # (Appendix C.6: add competencies when a real session hits one).
        logger.info("reduction_discarded_candidates", count=len(discarded), kept=len(kept))

    # A thin result still has to produce a real interview. Topping up from the
    # available bank is better than a two-question session, and the top-up is
    # taxonomy-ordered, so it stays deterministic.
    if len(kept) < MIN_COMPETENCIES:
        for competency_id in allowed:
            if competency_id not in kept:
                kept.append(competency_id)
            if len(kept) >= MIN_COMPETENCIES:
                break

    return Selectors(
        competency_ids=tuple(kept[:MAX_COMPETENCIES]),
        seniority=seniority,
        domain=domain,
        source=mode,
        discarded=tuple(discarded[:20]),
        model_version=f"{prompt.PROMPT_VERSION}/{result.model}",
    )
