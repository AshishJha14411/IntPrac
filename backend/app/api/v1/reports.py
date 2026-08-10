"""Candidate feedback report routes (§4.11)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import DbSession, ReportReader
from app.authz.perms import Perm
from app.authz.policy import authorize_owned
from app.core.errors import ConflictError, NotFoundError
from app.domain.enums import SessionPurpose, SessionStatus
from app.models.identity import Organization
from app.models.interview import InterviewSession
from app.services.report import build_report, progress_series

router = APIRouter(tags=["reports"])


async def _visible_or_403(db: DbSession, interview: InterviewSession) -> None:
    """FR-F1 / FR-F6.

    Practice mode shows the full report the moment grading finishes -- it is
    the product. Official mode defers to the org's configured visibility,
    defaulting to ``after_decision``.
    """
    if interview.purpose == SessionPurpose.PRACTICE:
        return
    organization = await db.get(Organization, interview.organization_id)
    policy = organization.candidate_feedback_visibility if organization else "after_decision"
    if policy == "always":
        return
    if policy == "none":
        raise ConflictError("Feedback for this interview is not shared with candidates.")
    if interview.status != SessionStatus.REVIEWED:
        raise ConflictError("Your feedback will be available once a decision has been made.")


@router.get("/sessions/{session_id}/report")
async def get_report(
    session_id: uuid.UUID, principal: ReportReader, db: DbSession, response: Response
) -> dict[str, Any]:
    interview = await db.get(InterviewSession, session_id)
    if interview is None:
        raise NotFoundError("Interview session not found.")
    authorize_owned(
        principal,
        owner_user_id=interview.user_id,
        organization_id=interview.organization_id,
        org_perm=Perm.SESSION_READ_ORG,
    )
    await _visible_or_403(db, interview)

    report = await build_report(db, session_id)
    # Per-viewer body, so revalidation is allowed and shared-cache reuse is not
    # (Appendix D.2). A public `max-age` here would leak one candidate's report
    # to another through any intermediary.
    response.headers["Cache-Control"] = "private, no-cache"
    return report.to_dict()


@router.get("/me/progress")
async def get_progress(principal: ReportReader, db: DbSession) -> dict[str, Any]:
    """FR-F4: competency scores over time, so practice has a visible arc."""
    return {"series": await progress_series(db, principal.user_id)}
