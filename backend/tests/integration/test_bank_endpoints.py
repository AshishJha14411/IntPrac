"""Bank read endpoints.

The counting test exists because an outer join to concepts fans a question row
out once per concept, so the obvious ``count()`` silently reports the concept
count as the question count -- a number that looks plausible and is wrong.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import BankQuestion, BankRubricConcept

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix


def test_taxonomy_lists_competencies(client: TestClient) -> None:
    body = client.get(f"{PREFIX}/bank/taxonomy").json()
    assert body["competencies"]
    first = body["competencies"][0]
    assert {"competency_id", "domain", "label", "authored_questions"} <= set(first)


def test_taxonomy_can_be_filtered_by_domain(client: TestClient) -> None:
    body = client.get(f"{PREFIX}/bank/taxonomy", params={"domain": "databases"}).json()
    assert body["competencies"]
    assert all(item["domain"] == "databases" for item in body["competencies"])


def test_coverage_counts_questions_not_join_rows(client: TestClient, db: Session) -> None:
    body = client.get(f"{PREFIX}/bank/coverage").json()
    expected_questions = db.query(BankQuestion).filter(BankQuestion.active.is_(True)).count()
    assert body["total_questions"] == expected_questions

    # And the concept count is genuinely larger, which is what makes the
    # inflated-count bug easy to miss: both numbers look reasonable alone.
    assert db.query(BankRubricConcept).count() > expected_questions
    assert sum(entry["concepts"] for entry in body["entries"]) > body["total_questions"]


def test_rubrics_are_not_exposed_to_candidates(client: TestClient) -> None:
    """The bank is browsable; the answer key is not.

    ``acceptable_signals`` are the exact phrases the grader matches on, so
    shipping them to a logged-out endpoint would hand over the marking scheme.
    """
    text = client.get(f"{PREFIX}/bank/taxonomy").text + client.get(f"{PREFIX}/bank/coverage").text
    for leak in ("acceptable_signals", "common_misconceptions", "neutral_wording", "signpost"):
        assert leak not in text
