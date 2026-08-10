"""Resume and JD contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PresignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0)
    label: str = Field(default="My resume", max_length=160)


class PresignResponse(BaseModel):
    """The API signs; the browser uploads. Bytes never touch us (FR-R2)."""

    resume_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    upload_url: str
    method: str
    headers: dict[str, str]
    expires_in: int
    #: Call this once the PUT succeeds so parsing can start.
    complete_url: str


class ResumeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    filename: str
    status: str
    failure_reason: str | None = None
    injection_flags: list[str] = Field(default_factory=list)
    parsed_at: datetime | None = None
    created_at: datetime


class ProfileItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    payload: dict
    #: FR-R5: the exact source span, so nothing looks invented.
    source_text: str
    source_span_start: int
    source_span_end: int
    prominence: int
    corrected_payload: dict | None = None


class ProfileResponse(BaseModel):
    version_id: uuid.UUID
    status: str
    identity: dict
    items: list[ProfileItemResponse]
    #: How much interview this resume can support, and what to add. Advice, not
    #: a gate -- see `services/resume_quality`.
    quality: dict = Field(default_factory=dict)


class ProfileItemCorrection(BaseModel):
    """FR-R7: corrections are an overlay with an audit trail, not an edit."""

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    payload: dict


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrections: list[ProfileItemCorrection] = Field(min_length=1, max_length=200)


class JDCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=40, max_length=60_000)


class JDVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_description_id: uuid.UUID
    version: int
    status: str
    thin: bool
    injection_flags: list[str] = Field(default_factory=list)
    created_at: datetime


class JDProfileResponse(BaseModel):
    version_id: uuid.UUID
    status: str
    role_title: str | None
    #: FR-J4: a thin JD warns rather than silently producing a weak interview.
    thin: bool
    requirements: list[dict]
    responsibilities: list[str]
