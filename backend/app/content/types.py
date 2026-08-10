"""Authoring types for the content library.

Bank content is authored offline and human-reviewed before it ships (FR-B2a).
LLM-drafting a rubric is fine *here* -- this is an authoring tool, not the
untrusted runtime path, and that distinction is what keeps IR-2 intact.

``validate_bank`` enforces the shipping bar (FR-B2b/c) at seed time and in CI,
so a mis-authored rubric fails loudly rather than quietly grading someone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.enums import ConceptWeight, QuestionArchetype, RubricFamily, Seniority

MIN_CORE_CONCEPTS = 2
MIN_SIGNALS_PER_CORE = 3
MIN_MISCONCEPTIONS = 2
#: A label answerable in this many words is a definition, not an idea.
TERMINOLOGY_SCREEN_MAX_WORDS = 3


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    concept_id: str
    label: str
    weight: ConceptWeight
    why_it_matters: str
    acceptable_signals: tuple[str, ...] = ()
    common_misconceptions: tuple[str, ...] = ()
    #: L2 hint: points at the area, names no term (FR-E4b).
    signpost: str | None = None


@dataclass(frozen=True, slots=True)
class GoldenSpec:
    label: str  # "strong" | "weak"
    transcript: str
    expected: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    competency_id: str
    seniority: Seniority
    neutral_wording: str
    concepts: tuple[ConceptSpec, ...]
    reframe_wording: str | None = None
    archetype: QuestionArchetype = QuestionArchetype.DEPTH
    rubric_family: RubricFamily = RubricFamily.CONCEPT
    expected_minutes: int = 4
    rubric_version: int = 1
    goldens: tuple[GoldenSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class CompetencySpec:
    competency_id: str
    domain: str
    label: str
    description: str | None = None


class BankValidationError(ValueError):
    pass


# --- authoring shorthands ---------------------------------------------------
def core(
    concept_id: str,
    label: str,
    why_it_matters: str,
    acceptable_signals: tuple[str, ...],
    signpost: str,
    common_misconceptions: tuple[str, ...] = (),
) -> ConceptSpec:
    return ConceptSpec(
        concept_id,
        label,
        ConceptWeight.CORE,
        why_it_matters,
        acceptable_signals,
        common_misconceptions,
        signpost,
    )


def sup(
    concept_id: str,
    label: str,
    why_it_matters: str,
    acceptable_signals: tuple[str, ...] = (),
    common_misconceptions: tuple[str, ...] = (),
) -> ConceptSpec:
    return ConceptSpec(
        concept_id,
        label,
        ConceptWeight.SUPPORTING,
        why_it_matters,
        acceptable_signals,
        common_misconceptions,
    )


def bonus(
    concept_id: str,
    label: str,
    why_it_matters: str,
    acceptable_signals: tuple[str, ...] = (),
) -> ConceptSpec:
    return ConceptSpec(
        concept_id, label, ConceptWeight.BONUS, why_it_matters, acceptable_signals
    )


def validate_question(spec: QuestionSpec) -> list[str]:
    """Return the reasons this rubric may not ship. Empty means it may."""
    problems: list[str] = []
    core = [c for c in spec.concepts if c.weight is ConceptWeight.CORE]
    key = f"{spec.competency_id}/{spec.seniority}"

    if len(core) < MIN_CORE_CONCEPTS:
        problems.append(f"{key}: needs >= {MIN_CORE_CONCEPTS} core concepts, has {len(core)}")

    for concept in spec.concepts:
        if not concept.why_it_matters.strip():
            # It is shown verbatim to the candidate; an empty one is a hole in
            # the feedback, not just missing metadata.
            problems.append(f"{key}/{concept.concept_id}: why_it_matters is required")

        # FR-B2c terminology screen: if a label can be "answered" with one
        # word, it tests vocabulary, which is exactly what this product refuses
        # to score.
        stripped = re.sub(r"[^\w\s-]", "", concept.label).strip()
        if len(stripped.split()) <= TERMINOLOGY_SCREEN_MAX_WORDS:
            problems.append(
                f"{key}/{concept.concept_id}: label '{concept.label}' is satisfiable by naming a "
                "term -- state the idea instead"
            )

        if concept.weight is ConceptWeight.CORE:
            if len(concept.acceptable_signals) < MIN_SIGNALS_PER_CORE:
                problems.append(
                    f"{key}/{concept.concept_id}: core concepts need >= "
                    f"{MIN_SIGNALS_PER_CORE} acceptable_signals"
                )
            if not concept.signpost:
                problems.append(
                    f"{key}/{concept.concept_id}: core concepts need an L2 signpost"
                )

    misconceptions = sum(len(c.common_misconceptions) for c in spec.concepts)
    if spec.concepts and misconceptions < MIN_MISCONCEPTIONS:
        problems.append(f"{key}: needs >= {MIN_MISCONCEPTIONS} common_misconceptions overall")

    ids = [c.concept_id for c in spec.concepts]
    if len(ids) != len(set(ids)):
        problems.append(f"{key}: duplicate concept_id")

    # FR-B2e: no rubric ships without a strong and a weak golden answer -- they
    # are the drift gate, and a gate with no fixtures is decoration.
    labels = {golden.label for golden in spec.goldens}
    if not {"strong", "weak"} <= labels:
        problems.append(f"{key}: needs at least one 'strong' and one 'weak' golden answer")

    return problems


def validate_bank(specs: list[QuestionSpec]) -> None:
    problems = [problem for spec in specs for problem in validate_question(spec)]
    if problems:
        raise BankValidationError(
            "Question bank failed the authoring bar (FR-B2b/c):\n  - "
            + "\n  - ".join(problems)
        )
