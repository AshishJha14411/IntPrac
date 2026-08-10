"""Liveness and readiness.

The distinction matters for NFR-S3: on SIGTERM, readiness must go false so the
load balancer stops sending *new* sessions here, while liveness stays true so
the orchestrator doesn't kill the process out from under the interviews still
running on it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.shutdown import drain_guard
from app.services import dispatch

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: DbSession, response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {"database": "unknown", "draining": drain_guard.draining}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    healthy = checks["database"] == "ok" and not drain_guard.draining
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if healthy else "not_ready",
        "active_sessions": drain_guard.active_sessions,
        "llm_enabled": settings.llm_enabled,
        # Whether a worker exists is deployment state the repo cannot see, and
        # a missing one fails *silently* -- events queue, the API keeps
        # returning 200, nothing is ever graded. Reporting the mode makes it a
        # curl instead of a console dig. See ADR 010.
        "dispatch": dispatch.dispatch_mode(),
        "checks": checks,
    }
