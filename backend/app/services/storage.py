"""Object storage: presigned direct upload and download.

FR-R2 / FR-M2: files go **straight from the browser to object storage**. The
API only signs the request and records metadata; bytes never stream through the
application server. That keeps a 10 MB PDF (or, later, hours of video chunks)
off the request path entirely.

Two endpoints are configured on purpose: ``s3_endpoint_url`` is how the API
reaches storage inside the compose network, ``s3_public_endpoint_url`` is what
the browser can resolve. Signing with the wrong one produces a URL that is
valid and unreachable, which is a confusing five minutes the first time.

**Provider (Appendix D.7).** "S3" here means the *protocol*, not the vendor.
MinIO serves it locally and **Google Cloud Storage serves it in production** via
its XML API and an HMAC key, so switching providers is four environment
variables and no code. The alternative -- the native ``google-cloud-storage``
SDK -- would trade the HMAC secret for the Cloud Run service account, which is
the better credential story, but signing a URL without a key file then needs an
IAM ``signBlob`` round trip per presign. Local signing with no extra call, and a
dev loop that still runs offline against MinIO, is worth one rotatable secret.

The XML API is not quite the whole S3 API, and ``delete_prefix`` below is where
that shows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_RESUME_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    object_key: str
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


@lru_cache(maxsize=2)
def _client(public: bool) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_public_endpoint_url if public else settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def validate_upload(content_type: str, size_bytes: int) -> str:
    """FR-R1: PDF or DOCX, <= 10 MB. Returns the file extension."""
    if content_type not in ALLOWED_RESUME_TYPES:
        raise ValidationError(
            "Only PDF and DOCX resumes are supported.",
            allowed=sorted(ALLOWED_RESUME_TYPES),
        )
    if size_bytes <= 0 or size_bytes > settings.max_upload_bytes:
        raise ValidationError(
            f"File must be between 1 byte and {settings.max_upload_bytes // (1024 * 1024)} MB.",
            max_bytes=settings.max_upload_bytes,
        )
    return ALLOWED_RESUME_TYPES[content_type]


def build_object_key(user_id: uuid.UUID, extension: str) -> str:
    """Namespaced by user so a per-user purge (FR-R9 / NFR-P) is a prefix delete."""
    return f"resumes/{user_id}/{uuid.uuid4().hex}{extension}"


def presign_upload(object_key: str, content_type: str, size_bytes: int) -> PresignedUpload:
    try:
        url = _client(public=True).generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket_uploads,
                "Key": object_key,
                "ContentType": content_type,
                # Signing the length pins the size server-side: a client cannot
                # sign for 1 MB and then upload 500.
                "ContentLength": size_bytes,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("presign_failed", error=str(exc))
        raise UpstreamUnavailableError("Storage is unavailable; try again shortly.") from exc

    return PresignedUpload(
        object_key=object_key,
        url=url,
        method="PUT",
        headers={"Content-Type": content_type, "Content-Length": str(size_bytes)},
        expires_in=settings.s3_presign_expiry_seconds,
    )


def presign_download(object_key: str) -> str:
    """Short-lived, signed, never public and never hot-linkable (FR-M4)."""
    return _client(public=True).generate_presigned_url(  # type: ignore[no-any-return]
        "get_object",
        Params={"Bucket": settings.s3_bucket_uploads, "Key": object_key},
        ExpiresIn=settings.s3_presign_expiry_seconds,
    )


def download_bytes(object_key: str) -> bytes:
    """Server-side fetch, used only by the async parse worker."""
    try:
        response = _client(public=False).get_object(
            Bucket=settings.s3_bucket_uploads, Key=object_key
        )
        return response["Body"].read()  # type: ignore[no-any-return]
    except (BotoCoreError, ClientError) as exc:
        raise UpstreamUnavailableError(f"Could not read {object_key}.") from exc


def object_exists(object_key: str) -> bool:
    try:
        _client(public=False).head_object(Bucket=settings.s3_bucket_uploads, Key=object_key)
        return True
    except ClientError:
        return False


def delete_prefix(prefix: str) -> int:
    """Right-to-deletion support (NFR-P): purge every object under a prefix.

    One request per object, deliberately. S3's batch delete (``POST ?delete``)
    does not exist in GCS's XML API, so the batched version worked against
    MinIO in dev and would have failed in production against the one call that
    must not fail quietly -- a deletion the user asked for and we reported as
    done. Deleting singly is the same operation on every provider.

    The cost is N requests instead of N/1000, on an operation that runs when a
    user leaves or a retention window closes. If that ever matters, the fix is a
    bucket lifecycle rule, not a batch API.
    """
    client = _client(public=False)
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket_uploads, Prefix=prefix):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=settings.s3_bucket_uploads, Key=item["Key"])
            deleted += 1
    return deleted
