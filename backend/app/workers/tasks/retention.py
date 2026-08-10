"""Retention and deletion jobs (NFR-P).

Retention is a **job**, not a promise in a policy document. If nothing deletes
on a schedule, the stated retention period is fiction -- and this app holds
video, voice, and resumes, among the most sensitive PII categories there is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import sync_session_scope
from app.models.documents import Resume, ResumeVersion
from app.models.identity import Organization, User
from app.models.interview import InterviewSession
from app.services import storage
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.retention.apply_retention")
def apply_retention() -> dict[str, int]:
    """Enforce each org's retention windows (NFR-P, G-009).

    Two windows, deliberately separate, because the two kinds of data carry
    different risk:

    * **Files** (``media_retention_days``) -- resumes and, later, recordings.
    * **Transcripts** (``transcript_retention_days``) -- the interview itself.

    This used to delete only the files, while the consent screen promised that
    everything went after 24 months. Transcripts therefore lived forever, and
    the promise was simply false. A retention period nothing enforces is not a
    policy, it is a sentence in a modal.

    Deleting the session cascades to its questions, answers, transcript
    segments and evaluations. The aggregate cost rows are deliberately kept:
    they carry no transcript and no identity, and losing them would erase the
    only record of what the system spent.
    """
    purged_objects = 0
    purged_sessions = 0
    with sync_session_scope() as db:
        for organization in db.execute(select(Organization)).scalars():
            now = datetime.now(UTC)

            media_cutoff = now - timedelta(days=organization.media_retention_days)
            versions = db.execute(
                select(ResumeVersion)
                .join(Resume, Resume.id == ResumeVersion.resume_id)
                .where(
                    Resume.organization_id == organization.id,
                    ResumeVersion.created_at < media_cutoff,
                )
            ).scalars()
            for version in versions:
                if not version.object_key:
                    continue
                try:
                    purged_objects += storage.delete_prefix(version.object_key)
                    version.object_key = ""
                except Exception as exc:
                    # Keep going: one unreachable object must not stop the rest
                    # of the sweep, or a single failure freezes retention for
                    # the whole organisation.
                    logger.warning(
                        "retention_delete_failed", key=version.object_key, error=str(exc)
                    )

            transcript_cutoff = now - timedelta(days=organization.transcript_retention_days)
            expired = db.execute(
                select(InterviewSession).where(
                    InterviewSession.organization_id == organization.id,
                    InterviewSession.created_at < transcript_cutoff,
                )
            ).scalars()
            for interview in expired:
                db.delete(interview)
                purged_sessions += 1

    logger.info(
        "retention_applied", purged_objects=purged_objects, purged_sessions=purged_sessions
    )
    return {"purged_objects": purged_objects, "purged_sessions": purged_sessions}


@celery_app.task(name="app.workers.tasks.retention.purge_user")
def purge_user(user_id: str) -> dict[str, int]:
    """Right to deletion (FR-R9 / NFR-P), and verifiable.

    Object keys are namespaced by user id precisely so this is a prefix delete
    rather than a hopeful walk over rows. Aggregate, non-identifying metrics
    may persist; everything that points at a person does not.
    """
    uid = uuid.UUID(user_id)
    with sync_session_scope() as db:
        objects = storage.delete_prefix(f"resumes/{uid}/")
        sessions = db.execute(
            select(InterviewSession).where(InterviewSession.user_id == uid)
        ).scalars()
        session_count = 0
        for interview in sessions:
            db.delete(interview)  # cascades to questions, answers, evaluations
            session_count += 1
        if user := db.get(User, uid):
            db.delete(user)
        logger.info("user_purged", user_id=user_id, sessions=session_count, objects=objects)
        return {"objects": objects, "sessions": session_count}
