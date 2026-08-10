"""Uvicorn entrypoint.

``timeout_graceful_shutdown`` is set slightly *below* compose's
``stop_grace_period`` so the drain finishes on our terms rather than being cut
short by SIGKILL (NFR-S3).
"""

from __future__ import annotations

import os

import uvicorn

from app.core.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - container-local bind; the edge is the boundary
        port=8080,
        reload=bool(int(os.getenv("UVICORN_RELOAD", "0"))) and settings.environment != "production",
        log_config=None,  # structlog owns logging
        access_log=False,
        timeout_graceful_shutdown=35,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
