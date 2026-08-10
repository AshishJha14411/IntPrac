"""Idempotent answer submission (FR-S8) and refresh-token reuse detection (FR-A3).

The concurrency test uses **real threads with a barrier**, not a mock. A test
that calls the endpoint twice sequentially passes against a completely broken
implementation, so it proves nothing about a race (Appendix D.5).
"""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import DocumentStatus
from app.models.identity import RefreshToken
from app.services.documents import parse_jd_version

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix

JD_TEXT = """
Backend Engineer
- indexing strategy and query planning
- transactions and acid
- rest api design and error contract design
- idempotency keys and rate limiting
- connection pooling and schema migration safety
"""


def _started_session(client: TestClient, db: Session) -> dict:
    response = client.post(f"{PREFIX}/jds", json={"title": "Role", "text": JD_TEXT})
    version_id = uuid.UUID(response.json()["id"])
    assert parse_jd_version(db, version_id) is DocumentStatus.READY
    db.flush()

    session_id = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 30,
            "jd_version_id": str(version_id),
        },
    ).json()["session"]["id"]
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start").json()
    return {"session_id": session_id, "turn": turn}


def test_retried_submit_returns_the_original_answer(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The dropped-connection case: the client resends, we must not double-record."""
    started = _started_session(client, db)
    payload = {
        "question_id": started["turn"]["question_id"],
        "transcript": (
            "It walks past all the skipped rows and discards them, so deep pages get slower. "
            "You seek from the last row you saw instead, with a tiebreaker for equal keys."
        ),
        "idempotency_key": "the-same-key-every-time",
    }
    url = f"{PREFIX}/sessions/{started['session_id']}/answers"

    first = client.post(url, json=payload)
    second = client.post(url, json=payload)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["answer_id"] == second.json()["answer_id"]
    assert second.json()["replayed"] is True


def test_different_keys_create_different_answers(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Idempotency must not collapse genuinely distinct submissions."""
    started = _started_session(client, db)
    url = f"{PREFIX}/sessions/{started['session_id']}/answers"
    base = {
        "question_id": started["turn"]["question_id"],
        "transcript": (
            "It walks past all the skipped rows and discards them, so deep pages get slower. "
            "You seek from the last row you saw instead."
        ),
    }
    first = client.post(url, json={**base, "idempotency_key": "key-one-aaaa"}).json()
    second_turn = first["next_turn"]
    assert second_turn is not None

    second = client.post(
        url,
        json={
            "question_id": second_turn["question_id"],
            "transcript": base["transcript"],
            "idempotency_key": "key-two-bbbb",
        },
    ).json()
    assert first["answer_id"] != second["answer_id"]


def test_answers_after_completion_are_rejected(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-S1: illegal transitions are rejected, not tolerated."""
    started = _started_session(client, db)
    url = f"{PREFIX}/sessions/{started['session_id']}/answers"
    turn = started["turn"]
    answer = (
        "It walks past all the skipped rows and discards them, so deep pages get slower. "
        "You seek from the last row you saw instead, with a tiebreaker for equal keys."
    )
    while True:
        body = client.post(
            url,
            json={
                "question_id": turn["question_id"],
                "transcript": answer,
                "idempotency_key": f"k-{uuid.uuid4().hex}",
            },
        ).json()
        if body["session_completed"]:
            break
        turn = body["next_turn"]

    late = client.post(
        url,
        json={
            "question_id": turn["question_id"],
            "transcript": answer,
            "idempotency_key": f"k-{uuid.uuid4().hex}",
        },
    )
    assert late.status_code == 409


# ---------------------------------------------------------------------------
# Refresh rotation
# ---------------------------------------------------------------------------
def test_refresh_rotates_the_token(client: TestClient) -> None:
    register = client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"rot-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Rotator",
        },
    )
    # G-011: the refresh token is cookie-only now, never in the body -- an XSS
    # must not be able to read a 30-day credential out of a fetch result.
    assert "refresh_token" not in register.json()
    original = client.cookies["interview_refresh"]

    rotated = client.post(f"{PREFIX}/auth/refresh")
    assert rotated.status_code == 200
    assert "refresh_token" not in rotated.json()
    assert client.cookies["interview_refresh"] != original, "rotation must change it"


def test_reusing_a_rotated_token_revokes_the_whole_family(
    client: TestClient, db: Session
) -> None:
    """FR-A3. Rotation alone protects nothing -- detecting the reuse does.

    A replayed token can only mean a copy exists somewhere it shouldn't, so the
    correct response is to invalidate every token in that family, not just the
    one presented.
    """
    register = client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"reuse-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Reuser",
        },
    )
    stolen = client.cookies["interview_refresh"]
    client.headers["Authorization"] = f"Bearer {register.json()['access_token']}"
    user_id = client.get(f"{PREFIX}/auth/me").json()["id"]

    assert client.post(f"{PREFIX}/auth/refresh").status_code == 200  # legitimate rotation

    # The attacker replays the old token.
    replay = client.post(f"{PREFIX}/auth/refresh", headers={"X-Refresh-Token": stolen})
    assert replay.status_code == 401
    assert "revoked" in replay.json()["detail"].lower()

    # Read committed state, not the identity map: the request mutated these
    # rows, and asserting against cached in-memory objects would pass even if
    # the write had been rolled back -- which is exactly the bug being tested.
    db.expire_all()
    family = db.query(RefreshToken).filter(RefreshToken.user_id == uuid.UUID(user_id)).all()
    assert len(family) == 2, f"expected the original plus one rotation, got {len(family)}"
    unrevoked = [str(token.id) for token in family if token.revoked_at is None]
    assert not unrevoked, (
        "reuse must revoke the entire family, not just the replayed token; "
        f"still live: {unrevoked}"
    )


def test_login_does_not_reveal_whether_an_account_exists(client: TestClient) -> None:
    missing = client.post(
        f"{PREFIX}/auth/login",
        json={"email": "nobody@example.com", "password": "a-long-enough-password-1"},
    )
    client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": "exists@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Exists",
        },
    )
    wrong = client.post(
        f"{PREFIX}/auth/login",
        json={"email": "exists@example.com", "password": "wrong-password-entirely"},
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"]


def test_another_users_session_is_not_readable(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Object-level access control: the id is not the authorisation."""
    started = _started_session(client, db)
    session_id = started["session_id"]

    other = client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Other",
        },
    )
    client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"

    response = client.get(f"{PREFIX}/sessions/{session_id}")
    assert response.status_code == 403


def test_concurrent_identical_submits_record_one_answer(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Two real threads, lined up on a barrier.

    A sequential double-post passes against a broken implementation; only an
    actual race exercises the unique constraint.
    """
    started = _started_session(client, db)
    url = f"{PREFIX}/sessions/{started['session_id']}/answers"
    payload = {
        "question_id": started["turn"]["question_id"],
        "transcript": (
            "It walks past all the skipped rows and discards them, so deep pages get slower. "
            "You seek from the last row you saw instead, with a tiebreaker for equal keys."
        ),
        "idempotency_key": "raced-key",
    }

    barrier = threading.Barrier(2)
    results: list[dict] = []
    lock = threading.Lock()

    def submit() -> None:
        barrier.wait(timeout=10)
        response = client.post(url, json=payload)
        with lock:
            results.append({"status": response.status_code, "body": response.json()})

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == 2
    successes = [r for r in results if r["status"] == 200]
    assert successes, f"both requests failed: {results}"
    answer_ids = {r["body"]["answer_id"] for r in successes}
    assert len(answer_ids) == 1, f"the race produced {len(answer_ids)} answers"
