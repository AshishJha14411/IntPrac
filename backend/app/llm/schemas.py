"""Schemas for every LLM boundary.

The LLM boundary is where types are genuinely fiction, so every model output is
runtime-validated before it can become a score (FR-E6a / Appendix D.8). Nothing
here is "best-effort parsed"; malformed output is retried, then quarantined for
a human.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import Verdict


class ConceptVerdict(BaseModel):
    """One verdict for one expected concept."""

    model_config = {"extra": "forbid"}

    concept_id: str
    verdict: Verdict
    #: FR-E2e: a quote from the candidate's own words, or an explicit absence.
    evidence_quote: str | None = None
    #: One line of "what could have been added", written to teach the idea.
    improvement_note: str | None = None

    @model_validator(mode="after")
    def _evidence_required(self) -> ConceptVerdict:
        """A verdict without evidence is invalid (FR-E2e).

        `missing` is the one verdict that may legitimately have no quote --
        there is nothing to quote. Everything else must point at words the
        candidate actually said, which is what makes a score explainable.
        """
        if self.verdict is not Verdict.MISSING and not (self.evidence_quote or "").strip():
            raise ValueError(
                f"verdict '{self.verdict}' for concept '{self.concept_id}' has no evidence quote"
            )
        return self


class GradingOutput(BaseModel):
    model_config = {"extra": "forbid"}

    concept_verdicts: list[ConceptVerdict] = Field(min_length=1)
    #: Informational only; carries zero weight in the score (FR-E2c).
    terminology_notes: list[str] = Field(default_factory=list)
    #: Whether the answer stayed on-topic but shallow -- drives follow-ups (FR-E5a).
    shallow: bool = False

    @field_validator("concept_verdicts")
    @classmethod
    def _unique_concepts(cls, value: list[ConceptVerdict]) -> list[ConceptVerdict]:
        ids = [verdict.concept_id for verdict in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate concept_id in grader output")
        return value

    def covers(self, expected_ids: set[str]) -> bool:
        return {verdict.concept_id for verdict in self.concept_verdicts} == expected_ids


GRADING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concept_verdicts", "terminology_notes", "shallow"],
    "properties": {
        "concept_verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["concept_id", "verdict", "evidence_quote", "improvement_note"],
                "properties": {
                    "concept_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["covered", "partial", "missing", "contradicted"],
                    },
                    "evidence_quote": {
                        "type": ["string", "null"],
                        "description": (
                            "A direct quote from the candidate's answer. Null ONLY when the "
                            "verdict is 'missing' and there is genuinely nothing to quote."
                        ),
                    },
                    "improvement_note": {
                        "type": ["string", "null"],
                        "description": (
                            "One sentence teaching the idea the candidate did not reach. "
                            "Explain the mechanism in plain words; never supply the jargon."
                        ),
                    },
                },
            },
        },
        "terminology_notes": {"type": "array", "items": {"type": "string"}},
        "shallow": {"type": "boolean"},
    },
}


class ReductionCandidate(BaseModel):
    model_config = {"extra": "forbid"}

    competency_id: str
    confidence: float = 0.5


class ReductionOutput(BaseModel):
    """═══ THE ONLY THING ALLOWED ACROSS THE TRUST BOUNDARY (§1.2) ═══

    Note what this model *cannot* express: there is no free-text field. Even if
    a hostile document convinces the reducer to emit instructions, there is
    nowhere for them to go -- and every ``competency_id`` is checked against the
    taxonomy before use (IR-4), so an invented one is dropped, not trusted.
    """

    model_config = {"extra": "forbid"}

    competencies: list[ReductionCandidate] = Field(default_factory=list)
    seniority_hint: str | None = None
    domain_hint: str | None = None


REDUCTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["competencies", "seniority_hint", "domain_hint"],
    "properties": {
        "competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["competency_id", "confidence"],
                "properties": {
                    "competency_id": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "seniority_hint": {"type": ["string", "null"]},
        "domain_hint": {"type": ["string", "null"]},
    },
}
