"""One error dialect, everywhere (Appendix D.1 #3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix


def _assert_problem(response: object, status: int) -> dict:
    assert response.status_code == status  # type: ignore[attr-defined]
    assert response.headers["content-type"].startswith("application/problem+json")  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert {"type", "title", "status", "detail"} <= set(body)
    assert body["status"] == status
    # Correlation id in the body: the user can paste it into a bug report and
    # it points at exactly one log line.
    assert body.get("request_id")
    return body


def test_malformed_body_never_becomes_a_500(client: TestClient) -> None:
    """Bad input must never produce a server error.

    (The precise status is the framework's call -- currently 400 for an
    undecodable body, 422 once it parses but fails validation. What matters
    here is that it is a client error, in problem+json, and that the error
    handler did not blow up on the way out. The specific bytes-in-``errors()``
    regression is pinned in ``tests/unit/test_error_handler.py``.)
    """
    response = client.post(
        f"{PREFIX}/auth/register",
        content=b"\x80\x81\x82 not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= response.status_code < 500, response.text
    _assert_problem(response, response.status_code)


def test_validation_error_lists_the_fields(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/auth/register", json={"email": "nope"})
    body = _assert_problem(response, 422)
    assert isinstance(body["errors"], list)
    assert body["errors"]


def test_unauthenticated_is_401_problem_json(client: TestClient) -> None:
    _assert_problem(client.get(f"{PREFIX}/sessions"), 401)


def test_not_found_is_problem_json(client: TestClient) -> None:
    _assert_problem(client.get(f"{PREFIX}/nope"), 404)


def test_duplicate_registration_is_409(client: TestClient) -> None:
    """The DB constraint is the arbiter; we translate the violation."""
    payload = {
        "email": "dupe@example.com",
        "password": "a-long-enough-password-1",
        "display_name": "Dupe",
    }
    assert client.post(f"{PREFIX}/auth/register", json=payload).status_code == 201
    body = _assert_problem(client.post(f"{PREFIX}/auth/register", json=payload), 409)
    assert body["type"].endswith("conflict")


def test_bad_cursor_is_422_not_500(client: TestClient, registered: dict) -> None:
    """A tampered cursor produces a clean error, never a crash."""
    response = client.get(f"{PREFIX}/sessions", params={"cursor": "!!!not-base64!!!"})
    _assert_problem(response, 422)


def test_correlation_id_is_echoed(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/health/live", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


def test_security_headers_are_present(client: TestClient) -> None:
    headers = client.get(f"{PREFIX}/health/live").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in headers
