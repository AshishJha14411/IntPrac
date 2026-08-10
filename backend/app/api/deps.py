"""Request dependencies: authentication, the principal, and shared gates.

⚠ Gate instances are module-level singletons. FastAPI's
``dependency_overrides`` keys on **object identity**, so an inline
``Depends(require(Perm.X))`` creates a fresh, un-overridable object and the
override in a test silently does nothing (Appendix D.2). Define once, import
everywhere.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.perms import Perm
from app.authz.policy import Principal, require_perm
from app.core.errors import AuthenticationError
from app.core.security import decode_access_token
from app.db.session import get_session
from app.domain.enums import OrgRole
from app.models.identity import OrgMember, User

ACCESS_COOKIE = "interview_access"
REFRESH_COOKIE = "interview_refresh"

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # Cookie fallback so the browser app works without touching localStorage.
    return request.cookies.get(ACCESS_COOKIE)


async def get_principal_optional(request: Request, db: DbSession) -> Principal | None:
    """Resolve the caller, or ``None``.

    The membership row is fetched **eagerly, in one query**. Reading a role off
    a lazily-loaded relationship inside an async request is the classic
    ``MissingGreenlet`` bug -- it manifests as a 500 for authenticated users on
    exactly the routes that check permissions, and nowhere else (Appendix D.4).
    """
    token = _bearer_token(request)
    if not token:
        return None
    payload = decode_access_token(token)
    user_id = uuid.UUID(payload["sub"])
    org_id = uuid.UUID(payload["org"])

    row = (
        await db.execute(
            select(OrgMember.role, User.email_verified_at)
            .join(User, User.id == OrgMember.user_id)
            .where(
                OrgMember.user_id == user_id,
                OrgMember.organization_id == org_id,
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        # Membership revoked since the token was minted: the token is valid and
        # the access is not.
        return None

    role, verified_at = row
    return Principal.build(
        user_id=user_id,
        organization_id=org_id,
        role=OrgRole(role),
        email_verified=verified_at is not None,
    )


async def get_principal(
    principal: Annotated[Principal | None, Depends(get_principal_optional)],
) -> Principal:
    if principal is None:
        raise AuthenticationError("Sign in to continue.")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
OptionalPrincipal = Annotated[Principal | None, Depends(get_principal_optional)]

GateFn = Callable[[Principal], Coroutine[Any, Any, Principal]]


def require(perm: Perm) -> GateFn:
    """Build a capability gate. Call at module scope, never inline."""

    async def gate(principal: CurrentPrincipal) -> Principal:
        require_perm(principal, perm)
        return principal

    gate.__name__ = f"require_{perm.name.lower()}"
    return gate


# --- shared gate instances (import these) ----------------------------------
can_manage_resume = require(Perm.RESUME_MANAGE)
can_manage_jd = require(Perm.JD_MANAGE)
can_start_session = require(Perm.SESSION_START)
can_answer = require(Perm.SESSION_ANSWER)
can_read_own_report = require(Perm.REPORT_READ_OWN)
can_manage_bank = require(Perm.BANK_MANAGE)

ResumeManager = Annotated[Principal, Depends(can_manage_resume)]
JDManager = Annotated[Principal, Depends(can_manage_jd)]
SessionStarter = Annotated[Principal, Depends(can_start_session)]
Answerer = Annotated[Principal, Depends(can_answer)]
ReportReader = Annotated[Principal, Depends(can_read_own_report)]
BankManager = Annotated[Principal, Depends(can_manage_bank)]


async def idempotency_key(request: Request) -> str | None:
    return request.headers.get("Idempotency-Key")


IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]


async def _noop() -> AsyncIterator[None]:  # pragma: no cover - placeholder for parity
    yield None
