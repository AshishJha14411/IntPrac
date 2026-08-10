"""The error handler's own failure mode (Appendix D.2).

⚠ The regression this file exists for: ``RequestValidationError.errors()`` can
contain raw ``bytes`` -- the offending request body. ``json.dumps`` chokes on
bytes, so the 422 handler raises *inside itself*, the outermost handler catches
it, and every malformed request turns into a 500. It is invisible until someone
posts something odd, and then it is invisible again because the 500 looks like
an ordinary bug rather than a bug in the thing that reports bugs.

``jsonable_encoder`` on the payload is the fix. This test drives the handler
directly with a bytes-carrying error so it fails if that call is ever removed.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers


@pytest.fixture()
def bytes_error_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom(request: Request) -> None:
        raise RequestValidationError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body", 0),
                    "msg": "Expecting value",
                    # The landmine: raw bytes inside the error payload.
                    "input": b"\x80\x81\x82 raw bytes here",
                    "ctx": {"error": ValueError("not serialisable either")},
                }
            ]
        )

    return app


def test_bytes_in_validation_errors_do_not_produce_a_500(bytes_error_app: FastAPI) -> None:
    with TestClient(bytes_error_app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["status"] == 422
    assert body["type"].endswith("validation-failed")
    # And the whole thing is genuinely serialisable, which is the actual claim.
    json.dumps(body)


def test_unhandled_exceptions_become_problem_json(bytes_error_app: FastAPI) -> None:
    @bytes_error_app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("kaboom")

    with TestClient(bytes_error_app, raise_server_exceptions=False) as client:
        response = client.get("/explode")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    # The message the user sees says nothing about the internals.
    assert "kaboom" not in response.text
