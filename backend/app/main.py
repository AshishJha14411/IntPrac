"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.idempotency import close_redis
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    AccessLogMiddleware,
    CorrelationMiddleware,
    CsrfOriginMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.shutdown import drain_guard

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "startup",
        environment=settings.environment,
        llm_enabled=settings.llm_enabled,
        api_prefix=settings.api_v1_prefix,
    )
    if not settings.llm_enabled:
        # Loud, because a silently-stubbed grader would make every score fake.
        logger.warning("llm_disabled_using_stub_adapter")
    try:
        yield
    finally:
        # NFR-S3: stop accepting new work, let live sessions finish.
        await drain_guard.drain()
        await close_redis()
        logger.info("shutdown_complete")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="AI Interview Platform",
        version="0.1.0",
        description=(
            "Interview practice and screening that scores understanding, not "
            "vocabulary. Answers are typed today; voice is P1 and grades the "
            "same transcript, so it can never score differently. "
            "See REQUIREMENTS_SPEC.md."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # Order matters: correlation must be outermost so every later log line and
    # every problem+json body carries the request id.
    app.add_middleware(SecurityHeadersMiddleware)
    # Inside the access log so a rejection is still recorded, outside the
    # routes so it runs before any handler touches state (G-010).
    app.add_middleware(CsrfOriginMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # cookie auth across the split origin
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "ETag"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
