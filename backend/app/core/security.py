"""Password hashing and token minting.

Argon2id for passwords; short-lived signed access tokens plus opaque,
rotating, hashed refresh tokens (FR-A3).

Refresh tokens are opaque random strings, not JWTs, and only their SHA-256 is
stored. A database leak therefore yields nothing replayable, and reuse of an
already-rotated token is detectable -- which is the property rotation exists
for in the first place.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_access_token(
    *, user_id: uuid.UUID, organization_id: uuid.UUID, role: str, email_verified: bool
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "ev": email_verified,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token expired.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token.") from exc
    if payload.get("typ") != "access":
        raise AuthenticationError("Wrong token type.")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Return ``(plaintext, sha256)``. Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds)


def sign_value(payload: str, *, ttl_seconds: int) -> str:
    """Sign a short-lived value so it can live in a cookie instead of a table.

    Used by the OAuth handshake (``services/oauth``) to carry ``state`` and the
    PKCE verifier across the round trip to Google. A server-side store would
    work too and would mean running one -- Redis is already fail-open here by
    design (NFR-S4), so hanging *login* off it would make a cache outage an
    outage. A signed cookie needs no store and still cannot be forged.

    HMAC-SHA256 over ``expiry.payload`` with the app's JWT secret. The expiry is
    inside the signed material, so it cannot be extended by editing the cookie.
    """
    expires_at = int(datetime.now(UTC).timestamp()) + ttl_seconds
    body = f"{expires_at}.{payload}"
    digest = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{digest}.{body}"


def verify_signed_value(token: str, *, max_age_seconds: int) -> str | None:
    """Return the payload, or ``None`` if forged, tampered with, or expired."""
    try:
        digest, expires_at, payload = token.split(".", 2)
    except ValueError:
        return None
    body = f"{expires_at}.{payload}"
    expected = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    # Constant time: a fast reject on the first wrong byte leaks the signature
    # one byte at a time.
    if not hmac.compare_digest(digest, expected):
        return None
    try:
        deadline = int(expires_at)
    except ValueError:
        return None
    now = int(datetime.now(UTC).timestamp())
    # Checked from both ends: the embedded expiry, and the caller's own maximum,
    # so a longer-lived token minted elsewhere cannot be replayed into a
    # shorter-lived flow.
    if now > deadline or deadline - now > max_age_seconds:
        return None
    return payload
