"""One place that turns an LLM call into ``usage_costs`` rows (NFR-C1).

This module exists because the rule was stated and then not followed. Three
code paths call a model -- grading, reduction, and question generation -- and
only grading recorded what it spent. The gap was invisible from inside: our own
totals looked plausible, they just did not match the provider's, and reduction
had never been counted at all since the day it was written.

So the recorder is extracted, works for both session sessions, and every call
site uses it. ``tests/unit/test_cost_accounting.py`` fails if a new
``.structured(`` appears in a module that does not.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domain.enums import CostKind
from app.llm.client import PRICING, LLMUsage
from app.models.ops import UsageCost


def cost_rows(
    usage: LLMUsage,
    *,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> list[UsageCost]:
    """Split one call into its input and output line items.

    Two rows rather than one so "what did this cost, and which half was it?"
    stays a GROUP BY. Zero-token sides are skipped -- a row saying nothing
    happened is noise in every later sum.
    """
    rates = PRICING.get(usage.model, PRICING["default"])
    rows: list[UsageCost] = []
    for kind, units, rate in (
        (CostKind.LLM_INPUT_TOKENS, usage.input_tokens, rates[0]),
        (CostKind.LLM_OUTPUT_TOKENS, usage.output_tokens, rates[1]),
    ):
        if not units:
            continue
        rows.append(
            UsageCost(
                session_id=session_id,
                user_id=user_id,
                kind=kind.value,
                units=float(units),
                usd=round(units * rate / 1_000_000, 8),
                model=usage.model,
            )
        )
    return rows


def record(
    db: Session,
    usage: LLMUsage,
    *,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    for row in cost_rows(usage, session_id=session_id, user_id=user_id):
        db.add(row)


def record_async(
    db: AsyncSession,
    usage: LLMUsage,
    *,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Same thing on the request path.

    ``db.add`` is not IO, so this needs no await -- but it takes an
    ``AsyncSession`` explicitly rather than a union, so a caller cannot pass
    the wrong one and find out at runtime.
    """
    for row in cost_rows(usage, session_id=session_id, user_id=user_id):
        db.add(row)
