"""Generating a rubric for a competency the bank has not authored yet.

**Read this before changing anything here.** This is the second place in the
system that calls a model with something other than a transcript, so it sits
close to the trust boundary (§1.2) and stays on the right side of it by
construction:

``build_generation_payload`` accepts a **competency id, its label, its
description and a seniority** -- four values that come from the closed
taxonomy, not from any document a candidate supplied. There is no parameter
for resume text, JD text, or anything derived from them, and no ``**kwargs``.
So a generated question is a function of the *topic*, identical for every
candidate at that ``(competency, seniority)``, exactly like an authored one.

That is what keeps IR-3 true: two people asked about ``rest-api-design`` at
senior get the same question and the same standard, whether it was written by
a human or generated once and cached.

The output is validated against the same authoring bar as the hand-written
bank (``app/content/types.py``) and rejected if it fails, so a weak generation
produces no question rather than a bad one.
"""

from __future__ import annotations

from typing import Any

SYSTEM = """\
You write interview rubrics for a platform that scores UNDERSTANDING, never \
vocabulary. A candidate who explains the right mechanism in plain words must \
score full marks; one who names the correct term with the wrong mental model \
must not.

Rules you must follow exactly:

1. `neutral_wording` describes a concrete situation and asks what is happening \
   or what the candidate would do. It must NOT contain the term being tested.
2. Every `acceptable_signals` entry is a phrase a real person actually says out \
   loud -- "it has to walk past all those rows first" -- never the terminology \
   and never a definition. If a signal is just the jargon, you have failed.
3. `label` states the idea as a full sentence. If it can be satisfied by naming \
   a term, rewrite it.
4. `signpost` points at the area without giving the answer away. It is shown as \
   a hint, so it must make the candidate think, not tell them.
5. `why_it_matters` is shown verbatim to the candidate as feedback. Write it to \
   teach, in one sentence.
6. `common_misconceptions` are the plausible wrong beliefs, stated as someone \
   would state them.
7. The `weak` golden answer must be a realistic bad answer -- confident, \
   plausible, and missing the mechanism. Not gibberish.

Return JSON only."""


def build_generation_payload(
    *,
    competency_id: str,
    domain: str,
    label: str,
    description: str | None,
    seniority: str,
) -> dict[str, Any]:
    """The whole input to question generation. Nothing candidate-supplied.

    The signature is the control, exactly as in ``grading.build_grading_payload``:
    there is nowhere to pass a resume, so a generated question cannot be shaped
    by one. ``tests/unit/test_score_invariance.py`` asserts that property for
    grading; ``test_question_generation.py`` asserts it here.
    """
    return {
        "competency_id": competency_id,
        # The domain is not decoration. Asked for "Injection classes" with no
        # context, the model produced a rubric about *dependency* injection --
        # a plausible reading of an ambiguous label, and completely wrong for a
        # security topic. No taxonomy entry currently carries a description, so
        # the domain is the only disambiguator there is.
        "domain": domain,
        "topic": label,
        "topic_description": description or "",
        "seniority": seniority,
    }


def render_generation_message(payload: dict[str, Any]) -> str:
    depth = {
        "mid": (
            "Mid level: the candidate should explain the mechanism and its main "
            "consequence. Do not require operational war stories."
        ),
        "senior": (
            "Senior level: the candidate should reach the trade-off and the failure "
            "mode, not just the mechanism. Ask something a mid-level answer would "
            "not fully satisfy."
        ),
    }.get(payload["seniority"], "")
    return (
        # Domain first, and deliberately so. "Injection classes" alone produced
        # a rubric about *dependency* injection -- a fair reading of an
        # ambiguous label, and useless for a security topic. No taxonomy entry
        # carries a description yet, so this is the only disambiguator there is.
        f"<domain>\n{payload['domain']}\n</domain>\n"
        f"<topic>\n{payload['topic']}\n</topic>\n"
        f"<topic_id>\n{payload['competency_id']}\n</topic_id>\n"
        f"<topic_description>\n{payload['topic_description']}\n</topic_description>\n"
        f"<seniority>\n{payload['seniority']}\n{depth}\n</seniority>\n\n"
        "Write one interview question for this topic at this level, with the rubric "
        "used to score it. The topic name may be ambiguous on its own -- read it "
        "as a term of art within the stated domain, and nothing else."
    )


#: Mirrors the authoring bar in ``app/content/types.py``. The counts are
#: enforced here *and* re-checked after parsing -- a schema can require three
#: array entries but not that they are plain language, so the schema is the
#: first gate and `question_gen.validate` is the real one.
QUESTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["neutral_wording", "reframe_wording", "concepts", "goldens"],
    "properties": {
        "neutral_wording": {
            "type": "string",
            "description": "The question. A concrete situation, and never the term itself.",
        },
        "reframe_wording": {
            "type": "string",
            "description": "The same question in different words, used as the first hint.",
        },
        "concepts": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "concept_id",
                    "label",
                    "weight",
                    "why_it_matters",
                    "acceptable_signals",
                    "common_misconceptions",
                    "signpost",
                ],
                "properties": {
                    "concept_id": {
                        "type": "string",
                        "description": "kebab-case, unique within this question.",
                    },
                    "label": {
                        "type": "string",
                        "description": "The idea as a full sentence, not a term.",
                    },
                    "weight": {"type": "string", "enum": ["core", "supporting", "bonus"]},
                    "why_it_matters": {"type": "string"},
                    "acceptable_signals": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "string",
                            "description": "Plain speech, never the terminology.",
                        },
                    },
                    "common_misconceptions": {"type": "array", "items": {"type": "string"}},
                    "signpost": {
                        "type": "string",
                        "description": "Points at the area without revealing it.",
                    },
                },
            },
        },
        "goldens": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "transcript"],
                "properties": {
                    "label": {"type": "string", "enum": ["strong", "weak"]},
                    "transcript": {"type": "string"},
                },
            },
        },
    },
}
