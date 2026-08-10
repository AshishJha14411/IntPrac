"""Seed the content library.

    docker compose run --rm seed

Idempotent: re-running updates existing rows rather than duplicating them, so
this is safe to run on every deploy.

The bank is **validated before anything is written** (FR-B2b/c). A rubric that
fails the authoring bar stops the seed rather than quietly shipping -- a rubric
nobody can defend is worse than a missing one, because it still produces a
score.
"""

from __future__ import annotations

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.bank_backend import QUESTIONS as BACKEND_QUESTIONS
from app.content.bank_databases import QUESTIONS as DATABASE_QUESTIONS
from app.content.bank_system_design import QUESTIONS as SYSTEM_DESIGN_QUESTIONS
from app.content.taxonomy import TAXONOMY, TAXONOMY_IDS
from app.content.types import BankValidationError, QuestionSpec, validate_bank
from app.core.logging import configure_logging, get_logger
from app.db.session import sync_session_scope
from app.models.content import BankQuestion, BankRubricConcept, Competency, GoldenAnswer

logger = get_logger(__name__)

ALL_QUESTIONS: tuple[QuestionSpec, ...] = (
    *DATABASE_QUESTIONS,
    *BACKEND_QUESTIONS,
    *SYSTEM_DESIGN_QUESTIONS,
)


def _seed_taxonomy(db: Session) -> int:
    existing = {
        row.competency_id: row for row in db.execute(select(Competency)).scalars().all()
    }
    written = 0
    for spec in TAXONOMY:
        row = existing.get(spec.competency_id)
        if row is None:
            db.add(
                Competency(
                    competency_id=spec.competency_id,
                    domain=spec.domain,
                    label=spec.label,
                    description=spec.description,
                    active=True,
                )
            )
            written += 1
        else:
            row.domain, row.label, row.description, row.active = (
                spec.domain,
                spec.label,
                spec.description,
                True,
            )
    db.flush()
    return written


def _seed_questions(db: Session) -> tuple[int, int]:
    written = updated = 0
    for spec in ALL_QUESTIONS:
        if spec.competency_id not in TAXONOMY_IDS:
            # A question outside the closed taxonomy could never be selected by
            # reduction (IR-4), so shipping it would be a silent dead letter.
            raise BankValidationError(
                f"{spec.competency_id} is not in the taxonomy; add it to taxonomy.py first"
            )

        question = (
            db.execute(
                select(BankQuestion).where(
                    BankQuestion.competency_id == spec.competency_id,
                    BankQuestion.seniority == spec.seniority.value,
                    BankQuestion.rubric_version == spec.rubric_version,
                )
            )
            .scalars()
            .one_or_none()
        )
        if question is None:
            question = BankQuestion(
                competency_id=spec.competency_id,
                seniority=spec.seniority.value,
                rubric_version=spec.rubric_version,
            )
            db.add(question)
            written += 1
        else:
            updated += 1
            # ⚠ Flush between the clear and the re-add. Both happen in one
            # flush otherwise, and SQLAlchemy orders the INSERTs before the
            # orphan DELETEs -- so re-seeding an existing rubric violates
            # `uq_bank_rubric_concepts_concept_id` on its own unchanged rows.
            # The seed is supposed to be idempotent; without this it works
            # exactly once.
            question.concepts.clear()
            question.golden_answers.clear()
            db.flush()

        question.rubric_family = spec.rubric_family.value
        question.archetype = spec.archetype.value
        question.neutral_wording = spec.neutral_wording
        question.reframe_wording = spec.reframe_wording
        question.expected_minutes = spec.expected_minutes
        question.active = True

        question.concepts = [
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
        ]
        question.golden_answers = [
            GoldenAnswer(
                label=golden.label,
                transcript=golden.transcript,
                expected_verdicts=dict(golden.expected),
            )
            for golden in spec.goldens
        ]
    db.flush()
    return written, updated


def main() -> int:
    configure_logging()
    try:
        # Validate the whole bank *before* touching the database. A partial
        # seed of a bank that fails review is worse than no seed.
        validate_bank(list(ALL_QUESTIONS))
    except BankValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    with sync_session_scope() as db:
        competencies = _seed_taxonomy(db)
        created, updated = _seed_questions(db)

    logger.info(
        "content_seeded",
        competencies_added=competencies,
        taxonomy_total=len(TAXONOMY),
        questions_created=created,
        questions_updated=updated,
        rubric_concepts=sum(len(spec.concepts) for spec in ALL_QUESTIONS),
    )
    print(
        f"Seeded {len(TAXONOMY)} competencies and {len(ALL_QUESTIONS)} rubrics "
        f"({created} new, {updated} updated), "
        f"{sum(len(s.concepts) for s in ALL_QUESTIONS)} concepts, "
        f"{sum(len(s.goldens) for s in ALL_QUESTIONS)} golden answers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
