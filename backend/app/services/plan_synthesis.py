"""Write a whole interview in one model call, from the candidate's documents.

Kept in its own module rather than added to ``question_gen``. That file's
docstring is an argument that generation never sees candidate text, and it is
still true of ``generate_for``; burying the document-aware path inside it would
make the one real exception in the system the hardest thing to find.

**What this is for.** The bank could only ask about topics somebody authored,
and only two and a half domains were ever authored -- so 32 of 129 competencies
were answerable and a frontend candidate got backend questions. Outside
software nobody on this project can author that content, or judge it if they
did. A generated interview about your actual work beats an authored interview
about somebody else's.

**What it costs.** Comparability. Two candidates no longer answer the same
questions, so the report is a personal development signal and not a ranking.
§1.2 was rewritten rather than left claiming otherwise.

**What it does not cost.** The grader. ``grading.build_grading_payload`` is
untouched and still receives only the rubric, the neutral wording and the
transcript. A document decides what you are asked about; it never talks to the
thing that scores you, and ``test_score_invariance.py`` still asserts that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.content.types import ConceptSpec, GoldenSpec, QuestionSpec, validate_question
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ConceptWeight, QuestionArchetype, Seniority
from app.llm.client import get_synthesis_client
from app.llm.prompts.plan_synthesis import (
    PLAN_JSON_SCHEMA,
    SYSTEM,
    build_synthesis_payload,
    render_synthesis_message,
)
from app.models.content import BankQuestion, BankRubricConcept, Competency, GoldenAnswer
from app.services import usage
from app.services.question_gen import GENERATED_RUBRIC_VERSION
from app.services.sanitize import sanitise_question, truncate_for_reduction

logger = get_logger(__name__)

_SLUG = re.compile(r"[^a-z0-9-]+")

#: Fields whose content is decided by a model that read the candidate's resume.
#: Anything that will be shown or spoken goes through ``sanitise_question``.
MAX_LABEL_WORDS = 8

# ── On regulated fields, and why there is no domain blocklist here ──────────
#
# There was one: any domain matching "clinical", "medical", "legal" and so on
# was refused, on the reasoning that a confidently wrong rubric about drug
# safety is misinformation with a score attached and nobody here could catch it.
# The reasoning is sound. The control was not, and the first real test showed
# why: a **Clinical Trial Manager** job description was refused on the word
# "clinical" and fell back to the bank, so an operations manager was asked about
# API versioning and async concurrency -- the precise failure this feature
# exists to fix, reintroduced by the thing meant to make it safe.
#
# Two separate mistakes. The match was far too coarse: trial management is site
# activation, CRO performance, TMF inspection readiness and enrolment strategy,
# and none of that is a medical claim. And the *failure direction* was wrong --
# falling back to a software bank is not a safe default for a non-software
# candidate, it is the original bug wearing a warning label.
#
# What actually holds the line is narrower and already in place: the system
# prompt forbids inventing specifics in regulated fields and requires questions
# about process, judgement and reasoning instead, and `validate_question` still
# rejects anything that misses the authoring bar. If a real refusal is ever
# needed it must surface to the candidate as a refusal, never as a silently
# irrelevant interview.


def _slug(value: str) -> str:
    return _SLUG.sub("-", value.strip().lower()).strip("-")[:80]


@dataclass(frozen=True)
class SynthesisedQuestion:
    """One planned question: the shared rubric, plus this candidate's wording."""

    question: BankQuestion
    #: Sanitised, document-grounded, and stored in ``SessionQuestion.framing_text``
    #: -- the field the model marks "COSMETIC ONLY ... never passed to the
    #: grader". ``None`` when sanitisation rejected it, in which case the
    #: candidate hears the neutral wording and the interview carries on.
    asked_prompt: str | None


@dataclass(frozen=True)
class SynthesisedPlan:
    domain: str
    questions: tuple[SynthesisedQuestion, ...]


def _to_spec(competency_id: str, seniority: Seniority, data: dict[str, Any]) -> QuestionSpec:
    """Shape the model's JSON into the struct the authored banks use.

    Going through ``QuestionSpec`` is what lets ``validate_question`` judge a
    synthesised rubric by exactly the bar a hand-written one clears.
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


def _clean_followups(raw: Any, concept_ids: set[str]) -> list[dict[str, str]]:
    """Keep only follow-ups that are sane and point at a concept we have.

    A follow-up naming a concept id the rubric does not contain is a
    hallucinated link, and it would drive the turn loop toward a gap that does
    not exist.
    """
    out: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        prompt = sanitise_question(item.get("prompt"))
        target = _slug(item.get("targets_concept_id") or "")
        if prompt and target in concept_ids:
            out.append({"prompt": prompt, "targets_concept_id": target})
    return out


async def _existing(
    db: AsyncSession, *, competency_id: str, seniority: Seniority
) -> BankQuestion | None:
    """A cache hit: we have already written this topic at this level."""
    return (
        await db.execute(
            select(BankQuestion)
            .options(selectinload(BankQuestion.concepts), selectinload(BankQuestion.golden_answers))
            .where(
                BankQuestion.competency_id == competency_id,
                BankQuestion.seniority == seniority.value,
                BankQuestion.active.is_(True),
            )
            .order_by(BankQuestion.rubric_version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _register_competency(
    db: AsyncSession, *, competency_id: str, domain: str, label: str
) -> None:
    """Add a taxonomy row for a topic the documents named and nobody authored.

    Marked ``origin='inferred'`` so a rubric that reads oddly can be traced back
    to a document rather than to the curated taxonomy.
    """
    if await db.get(Competency, competency_id) is not None:
        return
    db.add(
        Competency(
            competency_id=competency_id,
            domain=domain[:48],
            label=label[:200],
            active=True,
            origin="inferred",
        )
    )


async def synthesise_plan(
    db: AsyncSession,
    *,
    resume_text: str | None,
    jd_text: str | None,
    seniority: Seniority,
    question_count: int,
) -> SynthesisedPlan | None:
    """One call: documents in, a whole validated interview out.

    Returns ``None`` if the call or the parse failed, in which case planning
    falls back to the bank exactly as it did before synthesis existed. A thin
    interview is a worse outcome than a short one, but a *wrong* rubric is worse
    than both.
    """
    if not resume_text and not jd_text:
        return None

    payload = build_synthesis_payload(
        # The same truncation reduction uses. A 40-page CV is not more signal,
        # it is more input tokens.
        resume_text=truncate_for_reduction(resume_text) if resume_text else None,
        jd_text=truncate_for_reduction(jd_text) if jd_text else None,
        seniority=seniority.value,
        question_count=question_count,
    )

    try:
        result = await get_synthesis_client().structured(
            system=SYSTEM,
            user=render_synthesis_message(payload),
            schema=PLAN_JSON_SCHEMA,
            # Sized for the whole plan, not one question. The client treats
            # MAX_TOKENS as a failure rather than parsing a truncated object, so
            # a plan that overruns is retried by the caller at a smaller count
            # instead of being served with three questions missing.
            max_tokens=16000,
            effort=settings.llm_synthesis_effort,
        )
    except Exception as exc:
        logger.warning("plan_synthesis_failed", error=str(exc), count=question_count)
        return None

    domain = _slug(result.data.get("domain", "")) or "general"

    built: list[SynthesisedQuestion] = []
    seen: set[str] = set()
    rejected = 0

    for item in result.data.get("questions", []):
        label = (item.get("competency_label") or "").strip()
        competency_id = _slug(item.get("competency_id") or label)
        if not competency_id or competency_id in seen:
            continue
        if len(label.split()) > MAX_LABEL_WORDS:
            label = " ".join(label.split()[:MAX_LABEL_WORDS])
        seen.add(competency_id)

        cached = await _existing(db, competency_id=competency_id, seniority=seniority)
        if cached is not None:
            # Already written for someone else. Reuse the rubric, keep this
            # candidate's own wording.
            built.append(
                SynthesisedQuestion(cached, sanitise_question(item.get("prompt")))
            )
            continue

        spec = _to_spec(competency_id, seniority, item)
        problems = validate_question(spec)
        if problems:
            rejected += 1
            logger.info(
                "synthesised_question_rejected",
                competency_id=competency_id,
                problems=problems[:2],
            )
            continue

        await _register_competency(
            db, competency_id=competency_id, domain=domain, label=label or competency_id
        )

        concept_ids = {concept.concept_id for concept in spec.concepts}
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
            followups=_clean_followups(item.get("followups"), concept_ids),
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
                GoldenAnswer(label=g.label, transcript=g.transcript, expected_verdicts={})
                for g in spec.goldens
            ],
        )
        db.add(question)
        try:
            await db.flush()
        except IntegrityError:
            # Two sessions synthesised the same topic at once; the unique
            # constraint picked a winner. Read it back rather than failing the
            # plan (Appendix D.1 #2).
            await db.rollback()
            existing = await _existing(db, competency_id=competency_id, seniority=seniority)
            if existing is not None:
                built.append(
                    SynthesisedQuestion(existing, sanitise_question(item.get("prompt")))
                )
            continue

        built.append(SynthesisedQuestion(question, sanitise_question(item.get("prompt"))))

    # NFR-C1. One row for the whole plan, unattributed to a session on purpose:
    # the rubrics outlive this interview and are reused by everyone after it.
    usage.record_async(db, result.usage)

    logger.info(
        "plan_synthesised",
        domain=domain,
        asked_for=question_count,
        produced=len(built),
        rejected=rejected,
        usd=round(result.usage.usd, 5),
    )
    return SynthesisedPlan(domain=domain, questions=tuple(built)) if built else None
