"""Cheap, synchronous "did they touch this concept at all?" (FR-E5a).

**The problem this solves.** A rubric lists the concepts a good answer reaches.
The candidate answers once, covers four of five, and the fifth is reported as
*missing* -- having never been asked about. That reads as being marked down for
a question nobody put to them, and it is a fair complaint: a real interviewer
would have followed up.

Grading is the rigorous signal, but grading is deliberately off the critical
path (§8.1) and costs money per call, so it cannot decide whether to ask a
follow-up *while the candidate is sitting there*. This is the cheap
approximation that can: lexical overlap against the rubric's own
``acceptable_signals``, the same crude technique the offline stub grader uses,
at zero cost and no network.

**Why crude is the right trade here.** The only decision it drives is "ask one
more question". A false positive costs one extra follow-up. A false negative
costs nothing the real grader will not catch anyway. Precision is worth very
little; being synchronous and free is worth a lot.

It is deliberately *not* used for scoring. Nothing in this module reaches a
verdict.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Protocol

_TOKEN = re.compile(r"[a-z0-9]+")

#: Mirrors ``app/llm/stub_grader``. Common words say nothing about
#: understanding, so they are excluded from every comparison.
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

#: Below this overlap the answer shows no sign of having reached the concept.
#: Set well under the stub grader's own `covered` threshold (0.30) on purpose:
#: this decides whether to *ask*, so it should only fire when the concept looks
#: genuinely untouched, not merely thin. Thin answers earn a follow-up through
#: the separate length check.
TOUCHED_RATIO = 0.15


class HasSignals(Protocol):
    """Structural type, so this module needs no import from ``models``."""

    concept_id: str
    weight: str
    acceptable_signals: list[str]
    label: str


def _tokens(text: str) -> set[str]:
    return {word for word in _TOKEN.findall(text.lower()) if word not in _STOPWORDS}


def touched(transcript: str, signals: Iterable[str], label: str) -> bool:
    """True when the transcript shows any sign of reaching this concept."""
    pool = _tokens(" ".join([*signals, label]))
    if not pool:
        # Nothing to match against. Assume touched rather than badgering the
        # candidate about a concept the bank never described in plain words.
        return True
    return len(_tokens(transcript) & pool) / len(pool) >= TOUCHED_RATIO


def untouched_core_concepts(
    concepts: Sequence[HasSignals], transcript: str
) -> list[HasSignals]:
    """Core concepts the answer shows no sign of having reached.

    Core only. A supporting concept going unmentioned is not worth spending one
    of the candidate's two follow-ups on.
    """
    if not transcript.strip():
        return []
    return [
        concept
        for concept in concepts
        if concept.weight == "core"
        and not touched(transcript, concept.acceptable_signals or [], concept.label)
    ]
