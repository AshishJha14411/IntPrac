"""Deterministic stand-in for the model, used offline and in every test.

Why this exists rather than a mock: the interesting failure modes in this system
are in the *pipeline* (schema validation, evidence enforcement, hint
adjustment, score rollup, idempotent re-grade), not in the vendor call. A
deterministic adapter exercises all of them for free, and makes the
score-invariance property (§6.7) provable in CI instead of merely likely.

It scores by lexical overlap against the rubric's own ``acceptable_signals``
and ``common_misconceptions``. That is a crude proxy for understanding -- which
is exactly why the real grader is a language model -- but it is honest about
being one, and it never pretends to a verdict it cannot evidence.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")
#: Common words carry no signal about understanding, so they are excluded from
#: every overlap comparison below.
# fmt: off
_STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "do", "does", "for", "from", "has", "have", "how", "if", "in", "into",
    "is", "it", "its", "may", "might", "must", "not", "of", "on", "or",
    "should", "so", "such", "that", "the", "their", "then", "there",
    "these", "they", "this", "to", "was", "were", "what", "when", "where",
    "which", "who", "will", "with", "would", "you", "your",
])
# fmt: on


def _tokens(text: str) -> set[str]:
    return {word for word in _TOKEN.findall(text.lower()) if word not in _STOPWORDS}


def _extract(tag: str, text: str) -> str:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", text, re.DOTALL)
    return match.group(1) if match else ""


def _best_quote(answer: str, signal_tokens: set[str]) -> tuple[str | None, float]:
    """Return the sentence with the strongest overlap, and that overlap ratio.

    Quoting a real sentence rather than synthesising one keeps the stub honest
    about FR-E2e: if there is no sentence to point at, there is no evidence,
    and therefore no verdict above `missing`.
    """
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", answer) if part.strip()]
    best: tuple[str | None, float] = (None, 0.0)
    for sentence in sentences:
        overlap = _tokens(sentence) & signal_tokens
        if not signal_tokens:
            continue
        ratio = len(overlap) / len(signal_tokens)
        if ratio > best[1]:
            best = (sentence[:280], ratio)
    return best


def _grade(user_message: str) -> dict[str, Any]:
    import json

    rubric_raw = _extract("rubric", user_message)
    answer = _extract("candidate_answer", user_message)
    try:
        rubric = json.loads(rubric_raw) if rubric_raw else []
    except json.JSONDecodeError:
        rubric = []

    answer_tokens = _tokens(answer)
    verdicts: list[dict[str, Any]] = []
    covered = 0

    for concept in rubric:
        signals: list[str] = concept.get("acceptable_signals") or []
        misconceptions: list[str] = concept.get("common_misconceptions") or []
        label: str = concept.get("label", "")

        # A misconception match wins: right words, wrong model is `contradicted`,
        # never `covered` (FR-E2b).
        contradiction = None
        for misconception in misconceptions:
            tokens = _tokens(misconception)
            if tokens and len(answer_tokens & tokens) / len(tokens) >= 0.7:
                contradiction = misconception
                break

        pool = _tokens(" ".join([*signals, label]))
        quote, ratio = _best_quote(answer, pool)

        if contradiction is not None:
            quote = quote or (answer.strip()[:280] or None)
            verdict = "contradicted" if quote else "missing"
        elif ratio >= 0.30:
            verdict = "covered"
            covered += 1
        elif ratio >= 0.15:
            verdict = "partial"
        else:
            verdict, quote = "missing", None

        verdicts.append(
            {
                "concept_id": concept.get("concept_id", ""),
                "verdict": verdict,
                "evidence_quote": quote if verdict != "missing" else None,
                "improvement_note": (
                    None
                    if verdict == "covered"
                    else f"Explain, in your own words, the mechanism behind: {label}"
                ),
            }
        )

    return {
        "concept_verdicts": verdicts,
        "terminology_notes": [],
        "shallow": bool(rubric) and covered < max(1, len(rubric) // 2),
    }


def _reduce(user_message: str) -> dict[str, Any]:
    """Keyword-match document text against the allowed competency slugs.

    Slugs are readable by design (``offset-vs-keyset-pagination``), so splitting
    one on hyphens gives a usable set of match terms with no extra data.
    """
    allowed = [
        line.strip()
        for line in _extract("allowed_competencies", user_message).splitlines()
        if line.strip()
    ]
    document = " ".join(
        [
            _extract("resume_document", user_message),
            _extract("job_description_document", user_message),
        ]
    )
    document_tokens = _tokens(document)

    scored: list[tuple[float, str]] = []
    for competency_id in allowed:
        terms = {
            part
            for part in competency_id.split("-")
            if len(part) > 2 and part not in _STOPWORDS
        }
        if not terms:
            continue
        hits = len(terms & document_tokens)
        if hits:
            scored.append((hits / len(terms), competency_id))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return {
        "competencies": [
            {"competency_id": competency_id, "confidence": round(score, 3)}
            for score, competency_id in scored[:12]
        ],
        "seniority_hint": None,
        "domain_hint": None,
    }


def stub_response(user_message: str, schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if "concept_verdicts" in properties:
        return _grade(user_message)
    if "competencies" in properties:
        return _reduce(user_message)
    return {}
