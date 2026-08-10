"""Document parsing tasks (FR-R3 / FR-J2)."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.correlation import correlation
from app.core.logging import get_logger
from app.db.session import sync_session_scope
from app.services.documents import parse_jd_version, parse_resume_version
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="app.workers.tasks.parsing.parse_resume_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def parse_resume_task(version_id: str, payload: dict[str, Any] | None = None) -> str:
    with correlation(), sync_session_scope() as db:
        return parse_resume_version(db, uuid.UUID(version_id)).value


@celery_app.task(
    name="app.workers.tasks.parsing.parse_jd_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def parse_jd_task(version_id: str, payload: dict[str, Any] | None = None) -> str:
    with correlation(), sync_session_scope() as db:
        return parse_jd_version(db, uuid.UUID(version_id)).value
