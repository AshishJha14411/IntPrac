"""Prove the harness actually isolates (Appendix D.5).

If isolation is broken, every other test in the suite is reporting on state it
didn't create -- so this is checked directly rather than assumed. The pair
below writes in one test and asserts absence in the other; run in either order,
both must pass.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.identity import User

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix
MARKER = "isolation-probe@example.com"


def test_a_writes_a_marker_row(client: TestClient, db: Session) -> None:
    response = client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": MARKER,
            "password": "a-long-enough-password-1",
            "display_name": "Probe",
        },
    )
    assert response.status_code == 201
    assert db.query(User).filter(User.email == MARKER).count() == 1


def test_b_cannot_see_the_marker_row(db: Session) -> None:
    """The previous test's write must not survive into this one."""
    assert db.query(User).filter(User.email == MARKER).count() == 0


def test_search_path_is_the_private_schema(db: Session) -> None:
    """⚠ ``search_path`` is per *connection*, set in a pool ``connect`` event.

    Setting it once on one connection isolates only that connection, and every
    later checkout silently writes to ``public`` -- which looks like passing
    tests until two runs collide.
    """
    schema = db.execute(text("SELECT current_schema()")).scalar_one()
    assert schema.startswith("test_"), f"tests are running against '{schema}'"


def test_a_second_connection_also_lands_in_the_test_schema(engine: object) -> None:
    """A fresh checkout must land in the test schema too.

    This is the assertion that would have caught the whole class of bug: the
    first connection can be correctly configured while every subsequent one
    quietly isn't.
    """
    with engine.connect() as connection:  # type: ignore[attr-defined]
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    assert schema.startswith("test_"), f"a new connection landed in '{schema}'"


def test_uncommitted_ids_are_not_shared_across_tests(db: Session) -> None:
    """A sanity check that each test starts from the seeded baseline only."""
    from app.models.content import BankQuestion

    assert db.query(BankQuestion).count() > 0, "the seeded bank should be visible"
    assert db.query(User).filter(User.email.like("isolation-probe%")).count() == 0
    _ = uuid.uuid4()
