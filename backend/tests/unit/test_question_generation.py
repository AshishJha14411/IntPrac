"""Generated rubrics: the boundary, and the disambiguation.

Generation is the one place besides grading where a model is handed something
other than a transcript, so the property that matters most is *what it is not
given*. The rest of this file covers the failure that actually happened the
first time it ran.
"""

from __future__ import annotations

import inspect

from app.llm.prompts.question_gen import (
    QUESTION_JSON_SCHEMA,
    build_generation_payload,
    render_generation_message,
)


def _payload() -> dict:
    return build_generation_payload(
        competency_id="injection-classes",
        domain="security",
        label="Injection classes",
        description=None,
        seniority="senior",
    )


def test_generation_has_no_channel_for_candidate_text() -> None:
    """IR-3, at the second model call.

    The same argument as `build_grading_payload`: the signature is the control.
    A generated question is a function of a taxonomy entry and a seniority, so
    two candidates on the same competency get the same question and the same
    standard -- which is the only reason generation is allowed near scoring at
    all.
    """
    parameters = inspect.signature(build_generation_payload).parameters
    assert set(parameters) == {"competency_id", "domain", "label", "description", "seniority"}
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    ), "no **kwargs escape hatch"

    # The stronger property, and the one worth asserting: the message is a pure
    # function of the payload. Nothing else can reach the model, so a resume
    # cannot leak in through some other route either.
    payload = _payload()
    assert render_generation_message(payload) == render_generation_message(dict(payload))

    rendered = render_generation_message(payload).lower()
    # "candidate" is excluded from this list on purpose: it appears in our own
    # seniority instructions ("the candidate should explain..."), which is us
    # describing the task, not anything a candidate supplied. These are words
    # that could only have come from a document.
    for forbidden in ("resume", "curriculum vitae", "years of experience", "worked at"):
        assert forbidden not in rendered


def test_the_domain_reaches_the_model() -> None:
    """The bug this encodes, verbatim.

    Asked for "Injection classes" with no domain, the model produced a rubric
    about *dependency injection* -- a fair reading of an ambiguous label and
    completely wrong for a security topic. It would then have graded a
    candidate's security answer against a dependency-injection standard.

    No taxonomy entry carries a description yet, so the domain is the only
    thing distinguishing the two readings.
    """
    rendered = render_generation_message(_payload())
    assert "<domain>\nsecurity\n</domain>" in rendered
    assert "term of art within the stated domain" in rendered


def test_the_schema_enforces_the_authoring_bar() -> None:
    """The schema is the first gate; `validate_question` is the real one.

    A schema can require three signals but not that they are plain language, so
    both exist. This pins the part the schema *can* carry.
    """
    concept = QUESTION_JSON_SCHEMA["properties"]["concepts"]
    assert concept["minItems"] >= 3
    fields = concept["items"]["properties"]
    assert fields["acceptable_signals"]["minItems"] >= 3
    assert set(concept["items"]["required"]) >= {
        "label",
        "weight",
        "why_it_matters",
        "acceptable_signals",
        "signpost",
    }
    goldens = QUESTION_JSON_SCHEMA["properties"]["goldens"]
    assert goldens["minItems"] == 2, "a strong and a weak answer, the drift gate"
    assert QUESTION_JSON_SCHEMA["additionalProperties"] is False


def test_generated_rubrics_never_outrank_authored_ones() -> None:
    """Human authoring supersedes generation, never the other way round.

    `planning._load_bank` breaks ties on `rubric_version DESC`, so pinning
    generated rubrics at 0 means writing a real one later always wins -- with
    no cleanup step and nothing to remember.
    """
    from app.content.types import QuestionSpec
    from app.services.question_gen import GENERATED_RUBRIC_VERSION

    assert GENERATED_RUBRIC_VERSION == 0
    assert QuestionSpec.__dataclass_fields__["rubric_version"].default > GENERATED_RUBRIC_VERSION
