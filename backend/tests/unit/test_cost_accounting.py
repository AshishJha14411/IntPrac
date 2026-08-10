"""Every model call must leave a cost row (NFR-C1).

The rule was stated from day one and quietly not followed. Reduction had never
recorded a thing since it was written, and question generation shipped without
recording either -- so our own totals looked plausible and simply did not match
the provider's dashboard. Nothing failed; the numbers were just wrong, which is
the worst way for a cost control to break.

The check is deliberately crude -- it reads source for `.structured(` -- because
the failure it prevents is *forgetting*, and a new call site is exactly the
moment someone forgets. A subtler test would need the thing it is checking for
to already exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

#: Modules that call a model and are therefore expected to record what it cost.
#: A new one appearing here is the point: the test fails until it records.
CALLERS = sorted(
    path for path in APP.rglob("*.py") if ".structured(" in path.read_text(encoding="utf-8")
)


def test_there_are_call_sites_to_check() -> None:
    """A glob that matched nothing would make the real test vacuous."""
    assert CALLERS, "no `.structured(` call sites found -- has the client been renamed?"


@pytest.mark.parametrize("path", CALLERS, ids=lambda p: p.name)
def test_every_model_call_site_records_its_cost(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    records = "usage.record" in source or "UsageCost(" in source
    assert records, (
        f"{path.name} calls a model but never writes a cost row. "
        "Use `app.services.usage.record` / `record_async` — an unrecorded call "
        "is spend that exists on the provider's bill and nowhere in ours."
    )


def test_the_recorder_splits_input_from_output() -> None:
    """One row per direction, because the two are priced 8x apart.

    A single blended row would hide exactly the asymmetry that made the bill
    reducible in the first place: output tokens were 86% of spend.
    """
    from app.llm.client import LLMUsage
    from app.services.usage import cost_rows

    rows = cost_rows(LLMUsage(input_tokens=1000, output_tokens=1000, model="gemini-3.5-flash"))
    assert len(rows) == 2
    by_kind = {row.kind: row for row in rows}
    assert by_kind["llm_output_tokens"].usd > by_kind["llm_input_tokens"].usd, (
        "output must price higher than input, or PRICING has the columns swapped"
    )


def test_a_call_that_produced_nothing_records_nothing() -> None:
    """Zero-token rows are noise in every later sum."""
    from app.llm.client import LLMUsage
    from app.services.usage import cost_rows

    assert cost_rows(LLMUsage(input_tokens=0, output_tokens=0, model="stub")) == []


def test_an_unknown_model_is_priced_pessimistically() -> None:
    """An unrecognised model must over-estimate, never under-estimate.

    The failure we care about is a bill nobody saw coming, so `default` is the
    most expensive row rather than an average.
    """
    from app.llm.client import PRICING

    known = [rate for name, rate in PRICING.items() if name not in {"default", "stub"}]
    assert PRICING["default"][1] >= max(rate[1] for rate in known)
