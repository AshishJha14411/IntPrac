"""LLM adapter boundary.

NFR-C6 says this seam is "the single highest-leverage cost lever and should not
require a refactor to exercise", so the rest of the app depends on the
``LLMClient`` protocol and never on a vendor SDK. Swapping in a cheaper or
self-hosted model is a new class in this file, nothing else.

Reliability (NFR-S4): every call has a timeout budget, retries with jitter, and
a circuit breaker. When the breaker trips the session still completes and
grading is queued for later -- an interview never fails because a vendor did.

Determinism (FR-E6b): ``temperature=0`` narrows the distribution but does not
close it -- no hosted model is bit-reproducible, and thinking models least of
all. So reproducibility rests on the things that are actually pinned: a pinned
model id, a pinned prompt version, a pinned rubric version, and a schema the
output must satisfy. All four are stored on every evaluation, and IR-3's
invariance gate runs against the deterministic stub rather than the vendor.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def usd(self) -> float:
        """Rough per-call cost. Pricing lives here so §8.3 stays a real number."""
        rate = PRICING.get(self.model, PRICING["default"])
        return (self.input_tokens * rate[0] + self.output_tokens * rate[1]) / 1_000_000


# USD per million tokens (input, output), Gemini API paid tier, checked
# 2026-07-31 against https://ai.google.dev/gemini-api/docs/pricing.
#
# `default` is deliberately the *most expensive* row, not an average: an
# unknown model id should over-estimate spend, because the failure we care
# about is a bill nobody saw coming (§8.3), not a slightly pessimistic report.
PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.30, 2.50),
    # The 2.5 rows are kept for older accounts only: these models 404 for any
    # API key created recently, even though `models.list()` still returns them.
    "gemini-2.5-pro": (1.25, 10.00),  # ≤200k context; doubles above it
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "default": (2.50, 15.00),
    "stub": (0.0, 0.0),
}


@dataclass(slots=True)
class LLMResult:
    data: dict[str, Any]
    usage: LLMUsage
    model: str
    raw_text: str = ""


class LLMClient(Protocol):
    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 8000,
        effort: str = "high",
    ) -> LLMResult: ...


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
@dataclass
class CircuitBreaker:
    """Trips after ``threshold`` consecutive failures; half-opens after a cooldown.

    Deliberately tiny: at this scale a per-process breaker is the correct
    scope, and a distributed one would be the sort of machinery §2.2 rules out.
    """

    threshold: int = 4
    cooldown_seconds: float = 60.0
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            self._opened_at = None  # half-open: let one probe through
            self._failures = self.threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()
            logger.error("circuit_breaker_open", cooldown_seconds=self.cooldown_seconds)


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------
#: ``effort`` in the protocol -> Gemini's thinking level. Grading asks for
#: ``high`` because a verdict it cannot evidence is worse than a slow one;
#: reduction asks for ``medium`` because it is a classification against a fixed
#: taxonomy, not an open-ended judgement.
_THINKING_LEVELS = {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}

#: Terminal reasons that mean "the model chose not to answer". Retrying these
#: burns money to get the same answer, so they skip the retry loop entirely.
_REFUSAL_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


class GeminiLLMClient:
    def __init__(self, model: str, api_key: str) -> None:
        from google import genai
        from google.genai import types

        self._model = model
        self._types = types
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                # Milliseconds here, unlike almost every other timeout in this
                # codebase. Passing seconds gives you a 90ms budget and a
                # circuit breaker that trips on the first interview.
                timeout=int(settings.llm_timeout_seconds * 1000),
                # We own the retry policy so it composes with the breaker; two
                # independent retry layers turn one blip into six calls.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._breaker = CircuitBreaker()

    def _config(self, *, system: str, schema: dict[str, Any], max_tokens: int, effort: str) -> Any:
        types = self._types
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            # Standard JSON Schema, passed through untouched. `response_schema`
            # is the OpenAPI-subset alternative and the two are mutually
            # exclusive -- this one keeps `app/llm/schemas.py` as the single
            # definition of the contract, rather than a second dialect of it.
            response_json_schema=schema,
            max_output_tokens=max_tokens,
            temperature=0.0,
            thinking_config=types.ThinkingConfig(
                thinking_level=_THINKING_LEVELS.get(effort, "HIGH")
            ),
        )

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 8000,
        effort: str = "high",
    ) -> LLMResult:
        if self._breaker.is_open:
            raise UpstreamUnavailableError("The grading model is temporarily unavailable.")

        config = self._config(system=system, schema=schema, max_tokens=max_tokens, effort=effort)
        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model, contents=user, config=config
                )
            except Exception as exc:
                last_error = exc
                self._breaker.record_failure()
                if attempt < settings.llm_max_retries:
                    # Jittered backoff: a thundering herd of retries is how a
                    # blip becomes an outage.
                    delay = (2**attempt) * 0.5 + random.uniform(0, 0.5)  # noqa: S311
                    logger.warning("llm_retry", attempt=attempt + 1, delay=round(delay, 2))
                    await asyncio.sleep(delay)
                    continue
                break

            usage = self._usage(response)
            finish = self._finish_reason(response)
            if finish in _REFUSAL_REASONS:
                self._breaker.record_success()  # the vendor is up; it declined
                raise UpstreamUnavailableError("The model declined to grade this answer.")
            if finish == "MAX_TOKENS":
                # Thinking tokens come out of the same output budget, so a model
                # that reasons its way past `max_tokens` returns *truncated
                # JSON* -- which parses as a plausible score with concepts
                # silently missing. Refuse it and let the outbox retry.
                self._breaker.record_success()
                raise UpstreamUnavailableError(
                    "Model hit the output limit before finishing its answer."
                )

            text = (response.text or "").strip()
            self._breaker.record_success()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                # Schema-constrained output should make this impossible; if it
                # happens we surface it rather than best-effort parsing a score.
                raise UpstreamUnavailableError("Model returned unparseable output.") from exc
            return LLMResult(data=data, usage=usage, model=self._model, raw_text=text)

        raise UpstreamUnavailableError(
            f"LLM call failed after {settings.llm_max_retries + 1} attempts: {last_error}"
        )

    def _usage(self, response: Any) -> LLMUsage:
        """Token counts, with thinking counted as the output it is billed as.

        ``candidates_token_count`` excludes thoughts. Reporting only that would
        under-state the bill by however much the model reasoned -- which, on a
        thinking model asked for ``high`` effort, is most of the cost. NFR-C1
        says a session whose cost is unknown is a bug; a session whose cost is
        knowably wrong is a worse one.
        """
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return LLMUsage(model=self._model)
        return LLMUsage(
            input_tokens=meta.prompt_token_count or 0,
            output_tokens=(meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
            model=self._model,
        )

    @staticmethod
    def _finish_reason(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            # No candidate at all means a prompt-level block.
            return "SAFETY"
        reason = getattr(candidates[0], "finish_reason", None)
        return getattr(reason, "value", None) or str(reason or "")


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------
class StubLLMClient:
    """Deterministic offline adapter.

    Used when no API key is configured and in every test. It is *not* a mock in
    the "returns a canned blob" sense -- it implements a crude keyword overlap
    against the rubric's own acceptable signals, so the pipeline (schema
    validation, scoring, hint adjustment, report rollup) is exercised end to end
    without spending money or introducing nondeterminism.

    Because it is deterministic it is also what makes the score-invariance test
    (§6.7) meaningful in CI: identical transcripts must produce identical
    verdicts, and here that is provable rather than probable.
    """

    def __init__(self, model: str = "stub") -> None:
        self._model = model

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 8000,
        effort: str = "high",
    ) -> LLMResult:
        from app.llm.stub_grader import stub_response

        data = stub_response(user, schema)
        return LLMResult(
            data=data,
            usage=LLMUsage(input_tokens=0, output_tokens=0, model=self._model),
            model=self._model,
            raw_text=json.dumps(data),
        )


_grader: LLMClient | None = None
_reducer: LLMClient | None = None


def _build(model: str) -> LLMClient:
    if settings.llm_enabled and settings.gemini_api_key:
        return GeminiLLMClient(model, settings.gemini_api_key)
    return StubLLMClient()


def get_grader_client() -> LLMClient:
    global _grader
    if _grader is None:
        _grader = _build(settings.llm_grader_model)
    return _grader


def get_reducer_client() -> LLMClient:
    global _reducer
    if _reducer is None:
        _reducer = _build(settings.llm_reduction_model)
    return _reducer


def reset_clients() -> None:
    """Test hook."""
    global _grader, _reducer
    _grader = _reducer = None
