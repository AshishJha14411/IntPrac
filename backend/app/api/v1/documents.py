"""Resume and JD intake routes (§4.2, §4.3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, JDManager, ResumeManager
from app.authz.policy import authorize_owned
from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.enums import DocumentStatus
from app.models.documents import (
    JDProfile,
    JDVersion,
    JobDescription,
    Resume,
    ResumeProfile,
    ResumeVersion,
)
from app.schemas.documents import (
    CorrectionRequest,
    JDCreateRequest,
    JDProfileResponse,
    JDVersionResponse,
    PresignRequest,
    PresignResponse,
    ProfileItemResponse,
    ProfileResponse,
    ResumeVersionResponse,
)
from app.services import outbox, storage

router = APIRouter(tags=["documents"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------
@router.post(
    "/resumes/presign", response_model=PresignResponse, status_code=status.HTTP_201_CREATED
)
async def presign_resume(
    payload: PresignRequest, principal: ResumeManager, db: DbSession
) -> PresignResponse:
    """FR-R2: sign the upload, record metadata, get out of the way.

    The API never sees the bytes. It validates type and size, mints a
    short-lived presigned PUT, and stores a row in ``uploaded`` state.
    """
    extension = storage.validate_upload(payload.content_type, payload.size_bytes)

    resume = (
        await db.execute(
            select(Resume)
            .where(Resume.user_id == principal.user_id, Resume.label == payload.label)
            .limit(1)
        )
    ).scalars().one_or_none()
    if resume is None:
        resume = Resume(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            label=payload.label,
        )
        db.add(resume)
        await db.flush()

    # FR-R6: re-upload creates a new version. Completed interviews keep
    # pointing at the version they used.
    next_version = int(
        (
            await db.execute(
                select(func.coalesce(func.max(ResumeVersion.version), 0)).where(
                    ResumeVersion.resume_id == resume.id
                )
            )
        ).scalar_one()
    ) + 1

    object_key = storage.build_object_key(principal.user_id, extension)
    version = ResumeVersion(
        resume_id=resume.id,
        version=next_version,
        object_key=object_key,
        filename=payload.filename[:255],
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        status=DocumentStatus.UPLOADED,
    )
    db.add(version)
    await db.flush()

    presigned = storage.presign_upload(object_key, payload.content_type, payload.size_bytes)
    return PresignResponse(
        resume_id=resume.id,
        version_id=version.id,
        version=next_version,
        upload_url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        expires_in=presigned.expires_in,
        complete_url=f"{settings.api_v1_prefix}/resumes/versions/{version.id}/complete",
    )


async def _load_version(db: DbSession, version_id: uuid.UUID) -> tuple[ResumeVersion, Resume]:
    version = await db.get(ResumeVersion, version_id)
    if version is None:
        raise NotFoundError("Resume version not found.")
    resume = await db.get(Resume, version.resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    return version, resume


@router.post("/resumes/versions/{version_id}/complete", response_model=ResumeVersionResponse)
async def complete_resume_upload(
    version_id: uuid.UUID, principal: ResumeManager, db: DbSession
) -> ResumeVersionResponse:
    """Confirm the object landed, then queue parsing (FR-R3).

    We verify the object exists rather than trusting the client's word for it:
    a "complete" call for a PUT that never happened would otherwise queue a
    parse that always fails.
    """
    version, resume = await _load_version(db, version_id)
    authorize_owned(
        principal, owner_user_id=resume.user_id, organization_id=resume.organization_id
    )
    if not storage.object_exists(version.object_key):
        raise ConflictError("The upload has not finished yet.")

    version.status = DocumentStatus.PARSING
    outbox.enqueue(
        db,
        aggregate_type="resume_version",
        aggregate_id=version.id,
        event_type=outbox.EVENT_RESUME_UPLOADED,
    )
    return ResumeVersionResponse.model_validate(version)


@router.get("/resumes/versions/{version_id}", response_model=ResumeVersionResponse)
async def get_resume_version(
    version_id: uuid.UUID, principal: ResumeManager, db: DbSession
) -> ResumeVersionResponse:
    version, resume = await _load_version(db, version_id)
    authorize_owned(
        principal, owner_user_id=resume.user_id, organization_id=resume.organization_id
    )
    return ResumeVersionResponse.model_validate(version)


@router.get("/resumes/versions/{version_id}/profile", response_model=ProfileResponse)
async def get_resume_profile(
    version_id: uuid.UUID, principal: ResumeManager, db: DbSession
) -> ProfileResponse:
    version, resume = await _load_version(db, version_id)
    authorize_owned(
        principal, owner_user_id=resume.user_id, organization_id=resume.organization_id
    )
    profile = (
        await db.execute(
            select(ResumeProfile)
            .where(ResumeProfile.resume_version_id == version.id)
            .options(selectinload(ResumeProfile.items))
        )
    ).scalars().one_or_none()
    if profile is None:
        raise NotFoundError("This resume has not finished parsing yet.")
    return ProfileResponse(
        version_id=version.id,
        status=version.status,
        identity=profile.identity,
        items=[ProfileItemResponse.model_validate(item) for item in profile.items],
        quality=profile.quality or {},
    )


@router.patch("/resumes/versions/{version_id}/profile", response_model=ProfileResponse)
async def correct_resume_profile(
    version_id: uuid.UUID,
    payload: CorrectionRequest,
    principal: ResumeManager,
    db: DbSession,
) -> ProfileResponse:
    """FR-R7: corrections are stored as an overlay with an edit audit trail.

    The original extraction and its source span stay intact, so "what did the
    parser think, and what did the candidate change?" is always answerable.
    """
    from datetime import UTC, datetime

    version, resume = await _load_version(db, version_id)
    authorize_owned(
        principal, owner_user_id=resume.user_id, organization_id=resume.organization_id
    )
    profile = (
        await db.execute(
            select(ResumeProfile)
            .where(ResumeProfile.resume_version_id == version.id)
            .options(selectinload(ResumeProfile.items))
        )
    ).scalars().one_or_none()
    if profile is None:
        raise NotFoundError("This resume has not finished parsing yet.")

    by_id = {item.id: item for item in profile.items}
    now = datetime.now(UTC)
    for correction in payload.corrections:
        item = by_id.get(correction.item_id)
        if item is None:
            raise ValidationError(f"Unknown profile item {correction.item_id}.")
        item.corrected_payload = correction.payload
        item.corrected_at = now

    return ProfileResponse(
        version_id=version.id,
        status=version.status,
        identity=profile.identity,
        items=[ProfileItemResponse.model_validate(item) for item in profile.items],
        quality=profile.quality or {},
    )


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_resume(
    resume_id: uuid.UUID, principal: ResumeManager, db: DbSession
) -> dict[str, str]:
    """FR-R9: delete the resume and all derived data."""
    resume = await db.get(Resume, resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    authorize_owned(
        principal, owner_user_id=resume.user_id, organization_id=resume.organization_id
    )
    versions = (
        await db.execute(select(ResumeVersion).where(ResumeVersion.resume_id == resume.id))
    ).scalars().all()
    for version in versions:
        if version.object_key:
            storage.delete_prefix(version.object_key)
    await db.delete(resume)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Job descriptions
# ---------------------------------------------------------------------------
@router.post("/jds", response_model=JDVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_jd(
    payload: JDCreateRequest, principal: JDManager, db: DbSession
) -> JDVersionResponse:
    """FR-J1: paste a JD. Parsing is async, like resumes."""
    job = JobDescription(
        organization_id=principal.organization_id,
        created_by_user_id=principal.user_id,
        title=payload.title.strip(),
    )
    db.add(job)
    await db.flush()

    version = JDVersion(
        job_description_id=job.id,
        version=1,
        source="paste",
        raw_text=payload.text,
        status=DocumentStatus.PARSING,
    )
    db.add(version)
    await db.flush()

    outbox.enqueue(
        db,
        aggregate_type="jd_version",
        aggregate_id=version.id,
        event_type=outbox.EVENT_JD_SUBMITTED,
    )
    return JDVersionResponse.model_validate(version)


@router.get("/jds/versions/{version_id}", response_model=JDProfileResponse)
async def get_jd_profile(
    version_id: uuid.UUID, principal: JDManager, db: DbSession
) -> JDProfileResponse:
    version = await db.get(JDVersion, version_id)
    if version is None:
        raise NotFoundError("Job description not found.")
    job = await db.get(JobDescription, version.job_description_id)
    if job is None or job.organization_id != principal.organization_id:
        raise NotFoundError("Job description not found.")

    profile = (
        await db.execute(
            select(JDProfile)
            .where(JDProfile.jd_version_id == version.id)
            .options(selectinload(JDProfile.requirements))
        )
    ).scalars().one_or_none()
    if profile is None:
        raise NotFoundError("This job description has not finished parsing yet.")

    return JDProfileResponse(
        version_id=version.id,
        status=version.status,
        role_title=profile.role_title,
        thin=version.thin,
        requirements=[
            {
                "competency_id": requirement.competency_id,
                "weight": requirement.weight,
                "source_text": requirement.source_text,
            }
            for requirement in profile.requirements
        ],
        responsibilities=list(profile.responsibilities),
    )
