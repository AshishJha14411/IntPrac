"""Structured logging: JSON in production, human-readable in dev (Appendix D.7).

Every event carries the request/session correlation ids automatically, so a
single grep on request_id spans API -> worker -> vendor call.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings
from app.core.correlation import current_context


def _inject_correlation(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    event_dict.update(current_context())
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    # uvicorn's own access log duplicates our request middleware log line.
    logging.getLogger("uvicorn.access").disabled = True

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_correlation,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
