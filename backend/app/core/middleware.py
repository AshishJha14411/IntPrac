"""Request-scoped middleware: correlation, access log, security headers."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.correlation import REQUEST_ID_HEADER, new_id, set_request_id
from app.core.logging import get_logger

logger = get_logger("http")

Handler = Callable[[Request], Awaitable[Response]]


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Accept an inbound request id or mint one; echo it on the way out."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_id()
        set_request_id(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request, with the latency the §8.1 budgets track."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(elapsed_ms, 2),
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening. NFR-INJ7's companion: escape on render, lock down here."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(self), microphone=(self), geolocation=()"
        )
        # The API serves JSON only; a maximally restrictive CSP is free here and
        # blocks the "someone opened an API error page in a browser" class of bug.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if settings.environment == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


#: Methods that can change state. GET/HEAD/OPTIONS are exempt by definition.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """G-010: reject cross-site state changes that ride on an ambient cookie.

    The previous defence was an argument rather than a control: "every endpoint
    takes a JSON body, so nothing is a CORS-simple request, so everything is
    preflighted." Several cookie-authenticated POSTs take **no body at all** --
    refresh, logout, session start and abandon, upload completion. Those *are*
    simple requests, so a third-party page can submit them with a plain form
    and the browser will attach the cookie. CORS then blocks the attacker from
    *reading* the reply, which is no comfort when the damage is the write.

    ``SameSite=lax`` blocks this on a same-domain deployment. A split-domain one
    must set ``none`` and therefore has no SameSite protection at all, which is
    exactly the configuration this middleware exists for.

    Two rules, and the difference between them is the whole design:

    * **An ``Origin`` we do not allow is always rejected.** No legitimate
      caller sends one.
    * **A *missing* ``Origin`` is rejected only when ``SameSite=none``.**
      Under ``lax`` the browser already withholds the cookie on a cross-site
      unsafe request, so cookie-plus-cross-site cannot occur and a missing
      Origin means a non-browser client -- curl, the test suite, a script --
      which cannot be CSRF'd because nothing is tricking it into sending
      anything. Under ``none`` that protection is gone, and every browser does
      send Origin on such a request, so demanding one costs nothing and closes
      the hole.

    Failing closed in both modes was the first attempt and it was wrong: it
    broke every cookie-using script while adding no security in the mode where
    SameSite already holds.

    Bearer-token callers are unaffected: a token has to be deliberately
    attached, so it is not ambient, so it is not CSRF-able.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        if request.method not in _UNSAFE_METHODS:
            return await call_next(request)

        # No cookie, no ambient authority. Bearer clients and anonymous callers
        # both land here.
        has_cookie = any(name.startswith("interview_") for name in request.cookies)
        if not has_cookie or request.headers.get("authorization"):
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin is None:
            referer = request.headers.get("referer")
            if referer:
                parts = urlsplit(referer)
                origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme else None

        if origin is None and settings.auth_cookie_samesite != "none":
            # `lax`/`strict`: the browser would not have attached the cookie
            # cross-site, so there is nothing here to defend against.
            return await call_next(request)

        if origin not in settings.cors_origins:
            logger.warning(
                "csrf_origin_rejected",
                method=request.method,
                path=request.url.path,
                origin=origin or "<absent>",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "type": "https://interview.app/problems/forbidden",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": (
                        "This request did not come from a recognised origin. "
                        "If you are calling the API directly, use a bearer token."
                    ),
                    "instance": request.url.path,
                    "code": "csrf-origin-rejected",
                },
                media_type="application/problem+json",
            )
        return await call_next(request)
