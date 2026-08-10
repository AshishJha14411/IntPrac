"""Generate a rubric for a competency nobody has authored yet.

**What this changes about the system, stated plainly.** IR-2 and NFR-C3 say
planning makes zero model calls and every rubric comes from the bank. That was
the right default and it produced a real problem: question count is capped by
authored coverage, so a 45-minute resume-mode session planned *three*
questions. The bank has 32 competencies; the taxonomy has 129.

So the rule is relaxed deliberately and narrowly:

* **Only when the bank falls short of the target count.** An authored rubric is
  always preferred; generation fills a gap, it does not replace authoring.
* **Only in practice mode.** Official mode must stay comparable between
  candidates (FR-P4), and a rubric that appears mid-session is not comparable.
* **Once per (competency, seniority), then cached in the bank.** The second
  candidate on that topic pays nothing, which is NFR-C2's argument applied to
  a different asset.
* **Validated against the same authoring bar** as the hand-written banks. A
  generation that fails it produces no question rather than a bad one.

**The trust boundary is untouched.** Generation is a function of the taxonomy
entry and the seniority -- see ``build_generation_payload``, which has no
parameter for candidate text. Two people asked about the same competency get
the same question and the same standard, so IR-3 still holds by construction.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.content.types import (
    ConceptSpec,
    GoldenSpec,
    QuestionSpec,
    validate_question,
)
from app.core.logging import get_logger
from app.domain.enums import ConceptWeight, QuestionArchetype, Seniority
from app.llm.client import get_grader_client
from app.llm.prompts.question_gen import (
    QUESTION_JSON_SCHEMA,
    SYSTEM,
    build_generation_payload,
    render_generation_message,
)
from app.models.content import BankQuestion, BankRubricConcept, Competency, GoldenAnswer
from app.services import usage

logger = get_logger(__name__)

#: Generated rubrics are versioned apart from authored ones, so an authored
#: rubric written later always wins the `rubric_version DESC` tie-break in
#: `planning._load_bank`. Human authoring supersedes generation, never the
#: other way round.
GENERATED_RUBRIC_VERSION = 0

_SLUG = re.compile(r"[^a-z0-9-]+")


def _slug(value: str) -> str:
    return _SLUG.sub("-", value.strip().lower()).strip("-")[:80]


def _to_spec(competency_id: str, seniority: Seniority, data: dict[str, Any]) -> QuestionSpec:
    """Shape the model's JSON into the same struct the authored banks use.

    Going through ``QuestionSpec`` rather than writing rows directly is what
    lets ``validate_question`` judge a generated rubric by exactly the bar a
    human-written one has to clear.
    """
    concepts = tuple(
        ConceptSpec(
            _slug(concept.get("concept_id") or concept.get("label", "")),
            concept.get("label", "").strip(),
            ConceptWeight(concept.get("weight", "core")),
            concept.get("why_it_matters", "").strip(),
            tuple(signal.strip() for signal in concept.get("acceptable_signals", []) if signal),
            tuple(item.strip() for item in concept.get("common_misconceptions", []) if item),
            (concept.get("signpost") or "").strip() or None,
        )
        for concept in data.get("concepts", [])
    )
    goldens = tuple(
        GoldenSpec(golden.get("label", ""), golden.get("transcript", "").strip(), {})
        for golden in data.get("goldens", [])
    )
    return QuestionSpec(
        competency_id=competency_id,
        seniority=seniority,
        neutral_wording=data.get("neutral_wording", "").strip(),
        concepts=concepts,
        reframe_wording=(data.get("reframe_wording") or "").strip() or None,
        archetype=QuestionArchetype.DEPTH,
        expected_minutes=5 if seniority is Seniority.MID else 6,
        rubric_version=GENERATED_RUBRIC_VERSION,
        goldens=goldens,
    )


async def generate_for(
    db: AsyncSession, *, competency_id: str, seniority: Seniority
) -> BankQuestion | None:
    """Generate, validate and persist one rubric. Returns None if it fell short.

    Never raises on a bad generation: a thin plan is a worse outcome than a
    short one, but a *wrong* rubric is worse than both -- so failure here means
    the competency is simply skipped, exactly as an unauthored one always was.
    """
    competency = await db.get(Competency, competency_id)
    if competency is None:
        return None

    payload = build_generation_payload(
        competency_id=competency_id,
        domain=competency.domain,
        label=competency.label,
        description=competency.description,
        seniority=seniority.value,
    )
    try:
        result = await get_grader_client().structured(
            system=SYSTEM,
            user=render_generation_message(payload),
            schema=QUESTION_JSON_SCHEMA,
            max_tokens=6000,
            effort="high",
        )
    except Exception as exc:
        logger.warning("question_generation_failed", competency_id=competency_id, error=str(exc))
        return None

    spec = _to_spec(competency_id, seniority, result.data)
    problems = validate_question(spec)
    if problems:
        # The same bar the authored banks clear. A generation that misses it is
        # discarded rather than shipped with a warning nobody reads.
        logger.warning(
            "generated_rubric_rejected", competency_id=competency_id, problems=problems[:3]
        )
        return None

    question = BankQuestion(
        competency_id=spec.competency_id,
        seniority=spec.seniority.value,
        rubric_version=GENERATED_RUBRIC_VERSION,
        rubric_family=spec.rubric_family.value,
        archetype=spec.archetype.value,
        neutral_wording=spec.neutral_wording,
        reframe_wording=spec.reframe_wording,
        expected_minutes=spec.expected_minutes,
        generated=True,
        active=True,
        concepts=[
            BankRubricConcept(
                concept_id=concept.concept_id,
                ordinal=index,
                label=concept.label,
                weight=concept.weight.value,
                why_it_matters=concept.why_it_matters,
                signpost=concept.signpost,
                acceptable_signals=list(concept.acceptable_signals),
                common_misconceptions=list(concept.common_misconceptions),
            )
            for index, concept in enumerate(spec.concepts)
        ],
        golden_answers=[
            GoldenAnswer(label=golden.label, transcript=golden.transcript, expected_verdicts={})
            for golden in spec.goldens
        ],
    )
    db.add(question)
    try:
        await db.flush()
    except IntegrityError:
        # Two sessions generated the same competency at once. The unique
        # constraint on (competency_id, seniority, rubric_version) picked a
        # winner; read it back rather than failing the plan (Appendix D.1 #2).
        await db.rollback()
        logger.info("generated_rubric_race", competency_id=competency_id)
        return await load_generated(db, competency_id=competency_id, seniority=seniority)

    # NFR-C1: generation is a real model call and was billed like one, but
    # wrote no cost row -- so the bank quietly filled itself at a price nothing
    # recorded. Unattributed to a session on purpose: the rubric outlives this
    # interview and is reused by everyone after it.
    usage.record_async(db, result.usage)

    logger.info(
        "rubric_generated",
        competency_id=competency_id,
        seniority=seniority.value,
        concepts=len(spec.concepts),
        usd=round(result.usage.usd, 5),
    )
    return question


async def load_generated(
    db: AsyncSession, *, competency_id: str, seniority: Seniority
) -> BankQuestion | None:
    return (
        await db.execute(
            select(BankQuestion)
            .where(
                BankQuestion.competency_id == competency_id,
                BankQuestion.seniority == seniority.value,
                BankQuestion.active.is_(True),
            )
            # Eager, because the caller copies the rubric after an await
            # (Appendix D.4).
            .options(selectinload(BankQuestion.concepts))
            .order_by(BankQuestion.rubric_version.desc())
            .limit(1)
        )
    ).scalars().one_or_none()
