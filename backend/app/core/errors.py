"""RFC 7807 problem+json -- the single error dialect for the whole surface.

Non-negotiable #3 (Appendix D.1). There is no ad-hoc ``{"detail": ...}``
anywhere; every failure exits through here.

Two ⚠ traps live here, and both have the same shape: **the error handler must
not be able to fail**, because when it does, every deliberate 4xx becomes a
confusing 500 and the real problem is invisible.

1. ``RequestValidationError.errors()`` can contain raw ``bytes`` -- the
   offending request body. ``json.dumps`` chokes on it, and so does
   ``jsonable_encoder``, which decodes bytes as UTF-8 and raises on a body that
   isn't valid UTF-8. ``_safe()`` handles bytes before the encoder sees them.
2. Errors carry domain extras, and a domain field named ``status`` splatted
   into ``problem(status=...)`` is a ``TypeError`` at the call site. ``extra``
   is therefore a dict, and reserved members are namespaced rather than
   overwritten.

Both are pinned by ``tests/unit/test_error_handler.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import get_request_id
from app.core.logging import get_logger

logger = get_logger(__name__)

CONTENT_TYPE = "application/problem+json"
_TYPE_BASE = "https://interview.app/problems"


class AppError(Exception):
    """Base class for every deliberate, mapped failure."""

    status: int = 500
    title: str = "Internal Server Error"
    code: str = "internal-error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail or self.title
        self.extra = extra
        super().__init__(self.detail)


class NotFoundError(AppError):
    status, title, code = 404, "Not Found", "not-found"


class ConflictError(AppError):
    status, title, code = 409, "Conflict", "conflict"


class StaleResourceError(AppError):
    status, title, code = 409, "Conflict", "stale-resource"

    def __init__(self, detail: str = "This resource changed. Refresh and retry.") -> None:
        super().__init__(detail)


class ValidationError(AppError):
    status, title, code = 422, "Unprocessable Entity", "validation-failed"


class AuthenticationError(AppError):
    status, title, code = 401, "Unauthorized", "authentication-required"


class PermissionError_(AppError):
    status, title, code = 403, "Forbidden", "permission-denied"


class RateLimitedError(AppError):
    status, title, code = 429, "Too Many Requests", "rate-limited"


class SpendCapExceededError(AppError):
    """NFR-C5: degrade gracefully instead of producing a surprise bill."""

    status, title, code = 402, "Payment Required", "spend-cap-exceeded"


class IllegalTransitionError(AppError):
    """FR-S1: session state machine transitions are explicit; illegal ones fail."""

    status, title, code = 409, "Conflict", "illegal-state-transition"


class UpstreamUnavailableError(AppError):
    """NFR-S4: a vendor failed and the circuit breaker is open."""

    status, title, code = 503, "Service Unavailable", "upstream-unavailable"


#: RFC 7807 members an error's ``extra`` must never be able to overwrite.
_RESERVED = frozenset({"type", "title", "status", "detail", "instance", "request_id"})


def _safe(value: Any) -> Any:
    """Coerce anything into something ``json.dumps`` will accept.

    ⚠ ``jsonable_encoder`` alone is **not** enough here. It handles ``bytes``
    by calling ``.decode()``, which raises ``UnicodeDecodeError`` on a body
    that isn't valid UTF-8 -- exactly the case a malformed request produces.
    So bytes are handled before the encoder sees them, and anything the encoder
    still can't manage falls back to ``repr``. The error handler must not be
    able to fail; that is the whole point of it.
    """
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_safe(item) for item in value]
    try:
        return jsonable_encoder(value)
    except Exception:
        return repr(value)


def problem(
    status: int,
    title: str,
    code: str,
    detail: str,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a problem+json response.

    ⚠ ``extra`` is a **dict, not ``**kwargs``**. An error legitimately carries
    domain fields like ``status="completed"``, and splatting those into a
    signature that already has ``status`` raises ``TypeError`` at the call
    site -- turning a clean 409 into a 500 from inside the error handler.
    """
    body: dict[str, Any] = {
        "type": f"{_TYPE_BASE}/{code}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    if request_id := get_request_id():
        body["request_id"] = request_id
    # Extensions may not shadow the standard members either -- a domain
    # `status` is namespaced to `status_` rather than overwriting the HTTP one.
    for key, value in (extra or {}).items():
        body[f"{key}_" if key in _RESERVED else key] = _safe(value)
    return JSONResponse(status_code=status, content=body, media_type=CONTENT_TYPE)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            logger.error("app_error", code=exc.code, detail=exc.detail, path=request.url.path)
        return problem(
            exc.status,
            exc.title,
            exc.code,
            exc.detail,
            str(request.url.path),
            extra=exc.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(
            422,
            "Unprocessable Entity",
            "validation-failed",
            "The request body or parameters failed validation.",
            str(request.url.path),
            extra={"errors": exc.errors()},  # _safe() handles the bytes landmine
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        titles = {
            401: ("Unauthorized", "authentication-required"),
            403: ("Forbidden", "permission-denied"),
            404: ("Not Found", "not-found"),
            405: ("Method Not Allowed", "method-not-allowed"),
            429: ("Too Many Requests", "rate-limited"),
        }
        title, code = titles.get(exc.status_code, ("Error", "http-error"))
        return problem(
            exc.status_code, title, code, str(exc.detail or title), str(request.url.path)
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        # Non-negotiable #2: the DB constraint is the arbiter for uniqueness.
        # We never pre-check-then-insert; we catch the violation and translate.
        logger.info("integrity_violation", path=request.url.path)
        return problem(
            409,
            "Conflict",
            "conflict",
            "That value already exists or violates a constraint.",
            str(request.url.path),
        )

    @app.exception_handler(StaleDataError)
    async def _stale(request: Request, exc: StaleDataError) -> JSONResponse:
        return problem(
            409,
            "Conflict",
            "stale-resource",
            "This resource changed while you were editing it. Refresh and retry.",
            str(request.url.path),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return problem(
            500,
            "Internal Server Error",
            "internal-error",
            "An unexpected error occurred.",
            str(request.url.path),
        )
