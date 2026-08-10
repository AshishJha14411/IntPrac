"""Measure grader cost against grader accuracy, on the bank's own goldens.

"Can a cheaper model do this?" is an empirical question, and the bank already
contains the fixtures to answer it: every authored rubric ships a `strong` and
a `weak` golden answer with the verdicts a correct grader should produce
(FR-B2e). That makes accuracy measurable rather than a matter of taste.

    docker compose run --rm --no-deps api python scripts/grader_bench.py

Prints a table of model x thinking-level: tokens, cost, and agreement with the
expected verdicts. It spends real money -- a few cents -- which is the point:
the alternative is guessing about a per-session bill forever.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.llm.client import GeminiLLMClient
from app.llm.prompts.grading import (
    SYSTEM_PROMPT,
    RubricConceptView,
    build_grading_payload,
    render_user_message,
)
from app.llm.schemas import GRADING_JSON_SCHEMA, GradingOutput
from app.models.content import BankQuestion

MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
EFFORTS = ["low", "minimal"]
SAMPLE_QUESTIONS = 9  # x2 goldens = 18 gradings per combination


@dataclass
class Case:
    competency_id: str
    label: str
    concepts: tuple[RubricConceptView, ...]
    transcript: str
    expected: dict[str, str]


async def load_cases() -> list[Case]:
    async with AsyncSessionLocal() as db:
        questions = (
            await db.execute(
                select(BankQuestion)
                .where(BankQuestion.seniority == "senior", BankQuestion.generated.is_(False))
                .options(
                    selectinload(BankQuestion.concepts),
                    selectinload(BankQuestion.golden_answers),
                )
                .order_by(BankQuestion.competency_id)
                .limit(SAMPLE_QUESTIONS)
            )
        ).scalars().unique()

        cases: list[Case] = []
        for question in questions:
            concepts = tuple(
                RubricConceptView(
                    concept_id=concept.concept_id,
                    label=concept.label,
                    weight=concept.weight,
                    acceptable_signals=tuple(concept.acceptable_signals or ()),
                    common_misconceptions=tuple(concept.common_misconceptions or ()),
                )
                for concept in sorted(question.concepts, key=lambda c: c.ordinal)
            )
            for golden in question.golden_answers:
                if not golden.expected_verdicts:
                    continue
                cases.append(
                    Case(
                        competency_id=question.competency_id,
                        label=golden.label,
                        concepts=concepts,
                        transcript=golden.transcript,
                        expected=dict(golden.expected_verdicts),
                    )
                )
        return cases


async def score_one(client: GeminiLLMClient, case: Case, effort: str) -> tuple[int, int, float]:
    """Return (agreements, comparisons, usd) for one grading."""
    payload = build_grading_payload(
        neutral_wording="(bench)", concepts=case.concepts, transcript=case.transcript
    )
    result = await client.structured(
        system=SYSTEM_PROMPT,
        user=render_user_message(payload),
        schema=GRADING_JSON_SCHEMA,
        max_tokens=3000,
        effort=effort,
    )
    parsed = GradingOutput.model_validate(result.data)
    actual = {verdict.concept_id: verdict.verdict.value for verdict in parsed.concept_verdicts}
    # Only concepts the golden actually pins are compared -- a golden that says
    # nothing about a supporting concept is not evidence either way.
    comparisons = [(cid, want) for cid, want in case.expected.items() if cid in actual]
    agree = sum(1 for cid, want in comparisons if actual[cid] == want)
    return agree, len(comparisons), result.usage.usd


async def main() -> None:
    cases = await load_cases()
    if not cases:
        print("no golden answers with expected verdicts found -- run the seed first")
        return
    print(f"{len(cases)} golden answers, {len(MODELS) * len(EFFORTS)} combinations\n")
    print(f"{'model':26} {'effort':8} {'agree':>7} {'usd/grade':>10} {'proj/session':>13}")
    print("-" * 68)

    for model, effort in itertools.product(MODELS, EFFORTS):
        client = GeminiLLMClient(model, settings.gemini_api_key or "")
        agreements = comparisons = 0
        spent = 0.0
        for case in cases:
            try:
                agree, total, usd = await score_one(client, case, effort)
            except Exception as exc:  # a model that cannot do the task is a result
                print(f"{model:26} {effort:8} {'FAILED':>7}  {str(exc)[:30]}")
                break
            agreements += agree
            comparisons += total
            spent += usd
        else:
            rate = agreements / comparisons if comparisons else 0.0
            per_grade = spent / len(cases)
            # A 14-question session grades once per question.
            print(
                f"{model:26} {effort:8} {rate:>6.0%} {per_grade:>10.5f} "
                f"{per_grade * 14:>13.4f}"
            )


asyncio.run(main())
