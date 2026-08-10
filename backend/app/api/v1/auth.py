"""Authentication routes (FR-A1..A5).

Refresh-token rotation with **reuse detection**: presenting a token that was
already rotated can only mean it leaked, so the whole family is revoked rather
than just that one token (FR-A3).

⚠ Cookie ``path`` and the API prefix are coupled. A refresh cookie scoped to
``/auth`` stops being sent once routes move to ``/api/v1/auth`` -- so the path
is derived from the configured prefix rather than hardcoded (Appendix D.2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.deps import ACCESS_COOKIE, REFRESH_COOKIE, CurrentPrincipal, DbSession
from app.core.config import settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationError,
    problem,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.domain.enums import OrgRole
from app.models.identity import Organization, OrgMember, RefreshToken, User
from app.models.ops import AuditLog
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services import oauth, storage

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

REFRESH_COOKIE_PATH = f"{settings.api_v1_prefix}/auth"


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    common = {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        # `lax` still sends the cookie on top-level navigation (the OAuth
        # return trip) while blocking cross-site POSTs -- which is the CSRF
        # posture this app wants for a cookie-auth flow, and the default.
        #
        # A deploy that splits the browser app and the API across different
        # registrable domains has to set `none`, which gives that protection up.
        # What still stands in for it: every endpoint takes a JSON body, so no
        # state-changing request qualifies as a CORS-simple request, so all of
        # them are preflighted -- and the preflight is answered against an
        # explicit `CORS_ORIGINS` allowlist, never `*`. Deploying the two on one
        # registrable domain keeps `lax` and is the stronger posture.
        "samesite": settings.auth_cookie_samesite,
        "domain": settings.auth_cookie_domain or None,
    }
    response.set_cookie(
        ACCESS_COOKIE, access, max_age=settings.access_token_ttl_seconds, path="/", **common
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        **common,
    )


def _clear_cookies(response: Response) -> None:
    """G-012: delete with the *same* attributes the cookie was set with.

    A browser matches a deletion by name **and** domain and path. Omitting the
    configured domain, as this used to, leaves a domain-scoped cookie sitting
    in the jar while the response says 204 -- logout that looks successful and
    is not. Secure/samesite are included for the same reason: some browsers
    refuse to overwrite a ``Secure`` cookie from a non-Secure directive.
    """
    common = {
        "domain": settings.auth_cookie_domain or None,
        "secure": settings.auth_cookie_secure,
        "httponly": True,
        "samesite": settings.auth_cookie_samesite,
    }
    response.delete_cookie(ACCESS_COOKIE, path="/", **common)  # type: ignore[arg-type]
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, **common)  # type: ignore[arg-type]


async def _issue(db: DbSession, user: User, membership: OrgMember, response: Response,
                 user_agent: str | None) -> TokenResponse:
    access = create_access_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        role=membership.role,
        email_verified=user.email_verified_at is not None,
    )
    raw, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=uuid.uuid4(),
            token_hash=token_hash,
            expires_at=refresh_expiry(),
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    _set_cookies(response, access, raw)
    # G-011: the refresh token is set as an HttpOnly cookie and is deliberately
    # NOT in the body. It used to be returned "for non-browser clients", which
    # meant the browser got it too -- readable by any XSS straight out of the
    # mutation result, defeating HttpOnly for the flow it most protects. A
    # 30-day credential is the worst thing to hand to JavaScript. Non-browser
    # clients read the Set-Cookie header, or use the access token as a bearer.
    return TokenResponse(
        access_token=access,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    email = payload.email.lower()
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Never pre-check for uniqueness -- the constraint is the arbiter
        # (Appendix D.1 #2). This also closes the check-then-insert race.
        await db.rollback()
        raise ConflictError("An account with that email already exists.") from exc

    # A personal org per user: org scoping stays real without building the
    # org-management product at this scale (Appendix D.9).
    organization = Organization(
        name=f"{user.display_name}'s workspace",
        slug=f"u-{user.id.hex[:12]}",
        is_personal=True,
    )
    db.add(organization)
    await db.flush()
    membership = OrgMember(
        organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER.value
    )
    db.add(membership)
    await db.flush()

    logger.info("user_registered", user_id=str(user.id))
    return await _issue(db, user, membership, response, request.headers.get("user-agent"))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalars().one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        # One message for both cases: a distinct "no such account" is a user
        # enumeration oracle.
        raise AuthenticationError("Incorrect email or password.")
    if not user.is_active:
        raise AuthenticationError("This account is disabled.")

    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    membership = (
        await db.execute(select(OrgMember).where(OrgMember.user_id == user.id))
    ).scalars().first()
    if membership is None:
        raise AuthenticationError("This account has no workspace.")

    return await _issue(db, user, membership, response, request.headers.get("user-agent"))


@router.post("/refresh", response_model=None)
async def refresh(
    request: Request, response: Response, db: DbSession
) -> TokenResponse | JSONResponse:
    # An explicit header beats the ambient cookie: a non-browser client that
    # bothered to send one means it, and preferring the cookie would silently
    # refresh a different session than the caller asked for.
    raw = request.headers.get("X-Refresh-Token") or request.cookies.get(REFRESH_COOKIE) or ""
    if not raw:
        raise AuthenticationError("No refresh token presented.")

    # G-012: locked for the length of this transaction. Rotation is a
    # read-then-write, so two tabs refreshing at the same instant could both
    # read `rotated_at IS NULL`, both pass the reuse check, and both mint a
    # live descendant from one token that is supposed to be single-use --
    # turning the reuse detector into a coin flip. The second one now waits
    # here and then correctly sees a rotated token.
    token = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw))
            .with_for_update()
        )
    ).scalars().one_or_none()
    if token is None:
        raise AuthenticationError("Invalid refresh token.")

    now = datetime.now(UTC)

    # ── Reuse detection. A token that was already rotated is being presented
    # again, which means a copy exists somewhere it shouldn't. Rotation alone
    # doesn't protect anything; *this* does.
    if token.rotated_at is not None or token.revoked_at is not None:
        family = (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.family_id == token.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        for member in family:
            member.revoked_at = now
            member.revoked_reason = "reuse_detected"
        db.add(
            AuditLog(
                actor_user_id=token.user_id,
                action="auth.refresh_reuse_detected",
                resource_type="refresh_token_family",
                resource_id=token.family_id,
                detail={"revoked": len(family)},
            )
        )
        logger.warning("refresh_reuse_detected", user_id=str(token.user_id))

        # ⚠ We *return* the 401 instead of raising it, and that is the whole
        # point. Raising unwinds through the unit-of-work seam, which rolls the
        # transaction back -- taking the revocations and the audit row with it.
        # The attacker's token would still be live and the incident unrecorded.
        # A security side effect has to survive the failure of the request that
        # triggered it, so this path commits normally and hands back the error.
        problem_response = problem(
            401,
            "Unauthorized",
            "authentication-required",
            "Session revoked. Please sign in again.",
            str(request.url.path),
        )
        for cookie in response.headers.getlist("set-cookie"):
            problem_response.headers.append("set-cookie", cookie)
        _clear_cookies(problem_response)
        return problem_response

    if token.expires_at <= now:
        raise AuthenticationError("Refresh token expired.")

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account unavailable.")
    membership = (
        await db.execute(select(OrgMember).where(OrgMember.user_id == user.id))
    ).scalars().first()
    if membership is None:
        raise AuthenticationError("This account has no workspace.")

    token.rotated_at = now
    new_raw, new_hash = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=token.family_id,  # same family: that is what makes reuse detectable
            token_hash=new_hash,
            expires_at=refresh_expiry(),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    access = create_access_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        role=membership.role,
        email_verified=user.email_verified_at is not None,
    )
    _set_cookies(response, access, new_raw)
    return TokenResponse(
        access_token=access,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbSession) -> None:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
            )
        ).scalars().one_or_none()
        if token is not None:
            token.revoked_at = datetime.now(UTC)
            token.revoked_reason = "logout"
    _clear_cookies(response)


@router.get("/me", response_model=UserResponse)
async def me(principal: CurrentPrincipal, db: DbSession) -> UserResponse:
    user = await db.get(User, principal.user_id)
    if user is None:
        raise AuthenticationError("Account unavailable.")
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        organization_id=principal.organization_id,
        role=principal.role.value,
    )


# ---------------------------------------------------------------------------
# Google sign-in (FR-A1). See app/services/oauth.py for the security argument.
# ---------------------------------------------------------------------------
OAUTH_FLOW_COOKIE = "interview_oauth_flow"


def _flow_cookie_kwargs() -> dict[str, object]:
    return {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        # `lax`, always -- never inherited from AUTH_COOKIE_SAMESITE. Google's
        # callback is a top-level cross-site *navigation*, which `lax` allows
        # and `strict` would silently drop, breaking sign-in with no error.
        "samesite": "lax",
        "path": f"{settings.api_v1_prefix}/auth/google",
        "max_age": oauth.FLOW_TTL_SECONDS,
    }


@router.get("/google/status")
async def google_status() -> dict[str, object]:
    """So the login page can hide a button that cannot work.

    ``hint`` is populated **only outside production**. Hiding the button is
    right for users and baffling for whoever is running the app locally and
    wondering where it went, so the answer is shown to them and to nobody else.
    A production login page must never explain its own configuration.
    """
    enabled = oauth.is_configured()
    body: dict[str, object] = {"enabled": enabled}
    if not enabled and settings.environment != "production":
        body["hint"] = (
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, then "
            "`docker compose up -d api`. Redirect URI to register with Google: "
            f"{settings.google_redirect_uri}"
        )
    return body


@router.get("/google/login")
async def google_login(request: Request, next: str = "/dashboard") -> RedirectResponse:
    if not oauth.is_configured():
        raise NotFoundError("Google sign-in is not configured on this deployment.")
    begun = oauth.begin(oauth.safe_next(next))
    redirect = RedirectResponse(begun.url, status_code=status.HTTP_303_SEE_OTHER)
    # The cookie must ride on *this* response, the redirect itself -- setting it
    # on a different response object is how it silently never reaches the
    # browser and every callback then fails validation.
    redirect.set_cookie(OAUTH_FLOW_COOKIE, begun.flow_cookie, **_flow_cookie_kwargs())  # type: ignore[arg-type]
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish the handshake, then hand the browser back to the app.

    Failures redirect rather than render a problem+json body: this URL is
    reached by a *browser navigation*, so a JSON error would leave the user
    staring at raw text. The reason travels as a query parameter the login page
    can explain.
    """
    front = settings.frontend_base_url.rstrip("/")

    def bounce(reason: str) -> RedirectResponse:
        response = RedirectResponse(
            f"{front}/login?error={reason}", status_code=status.HTTP_303_SEE_OTHER
        )
        response.delete_cookie(OAUTH_FLOW_COOKIE, path=f"{settings.api_v1_prefix}/auth/google")
        return response

    if error or not code:
        # The user pressed "cancel" on the consent screen. Not an incident.
        logger.info("oauth_declined", error=error)
        return bounce("cancelled")

    try:
        flow = oauth.read_flow(request.cookies.get(OAUTH_FLOW_COOKIE), state)
        claims = await oauth.exchange_and_verify(code, flow["verifier"])
        user, membership = await oauth.resolve_user(db, claims)
    except (ValidationError, UpstreamUnavailableError) as exc:
        logger.warning("oauth_callback_failed", error=str(exc))
        return bounce("failed")

    landing = oauth.safe_next(flow.get("next"))
    response = RedirectResponse(f"{front}{landing}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OAUTH_FLOW_COOKIE, path=f"{settings.api_v1_prefix}/auth/google")
    # Same cookies as password sign-in, so everything downstream -- refresh
    # rotation, reuse detection, /auth/me -- is one code path, not two.
    tokens = await _issue(db, user, membership, response, request.headers.get("user-agent"))
    logger.info("oauth_login", user_id=str(user.id), provider=oauth.PROVIDER)
    del tokens  # the browser has the cookies; the body of a redirect is unread
    return response


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    principal: CurrentPrincipal, response: Response, db: DbSession
) -> None:
    """Delete this account and everything belonging to it (FR-R9 / NFR-P).

    G-009: the other half of a promise the product was making and could not
    keep. Consent says data can be deleted at any time; until now nothing could.

    Deliberately synchronous rather than queued. A deletion that returns 204 and
    then fails in a worker is the worst outcome available -- the user has been
    told it is gone. Doing it inside the request means the unit-of-work seam
    either commits the whole thing or none of it, and any failure reaches the
    person who asked.

    Object storage is not transactional, so files are removed first: a failure
    there aborts before the rows go, leaving a state that can be retried. The
    reverse order would orphan the objects with nothing left pointing at them.
    """
    user_id = principal.user_id
    user = await db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Account unavailable.")

    objects = await run_in_threadpool(storage.delete_prefix, f"resumes/{user_id}/")

    # Written before the delete, and pointing at an id that will no longer
    # exist: the audit row is the evidence the deletion happened, so it must
    # not be a child of the thing being deleted (the FK is ON DELETE SET NULL).
    db.add(
        AuditLog(
            actor_user_id=None,
            organization_id=principal.organization_id,
            action="account.deleted",
            resource_type="user",
            resource_id=user_id,
            detail={"objects_deleted": objects},
        )
    )
    await db.delete(user)
    _clear_cookies(response)
    logger.info("account_deleted", user_id=str(user_id), objects=objects)
