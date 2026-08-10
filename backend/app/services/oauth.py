"""Google sign-in (OIDC authorization code + PKCE).

Ported from the v1 project's flow, with three deliberate changes. Each closes
something that flow left open, so they are documented rather than silently
"improved":

1. **``state`` and PKCE.** v1 sent neither. Without ``state`` the callback will
   accept *any* valid code, including one an attacker obtained for their own
   account and then fed to your browser -- login CSRF, which quietly lands your
   subsequent interviews in their account. PKCE additionally makes an
   intercepted code useless without the verifier. Both live in a short-lived
   signed cookie, so there is no server-side session store to run and this
   still works on a scale-to-zero host (ADR 010).

2. **Email linking requires ``email_verified``.** v1 matched an existing
   account on the provider's email alone. Any provider that will issue an
   unverified email claim then becomes an account-takeover path into a
   password account. Google does verify, but relying on that implicitly is
   the bug -- so we check, and refuse to link when it is absent.

3. **The unique constraint decides, not a prior read.** ``(provider, subject)``
   is unique and an ``IntegrityError`` is translated, rather than a
   check-then-insert that two simultaneous first sign-ins can both pass
   (Appendix D.1 #2).

Nothing here commits: the request seam owns the transaction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError, ValidationError
from app.core.logging import get_logger
from app.core.security import sign_value, verify_signed_value
from app.domain.enums import OrgRole
from app.models.identity import Organization, OrgMember, User
from app.models.oauth import OAuthAccount

logger = get_logger(__name__)

PROVIDER = "google"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

#: The handshake must complete in one sitting. Long enough for a slow consent
#: screen, short enough that a leaked cookie is worthless by the time it is
#: found.
FLOW_TTL_SECONDS = 600

#: Tolerance for clock skew when validating Google's ID token. Not optional:
#: container clocks drift, Docker Desktop's VM clock jumps after the host
#: sleeps, and a token issued one second in *our* future is otherwise a hard
#: sign-in failure with a baffling message.
CLOCK_SKEW_LEEWAY_SECONDS = 60


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    url: str
    #: Opaque, signed, HttpOnly. Carries the state and the PKCE verifier.
    flow_cookie: str


def begin(next_path: str = "/dashboard") -> AuthorizationRequest:
    """Build the consent-screen URL and the cookie that will validate its reply."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

    # `next` is carried in the cookie rather than the URL so it cannot be used
    # as an open redirect: the callback only ever reads it from here, and a
    # relative path is enforced on the way out.
    payload = json.dumps({"state": state, "verifier": verifier, "next": next_path})

    query = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Ask for a fresh consent-free sign-in but let Google pick the account:
        # `select_account` avoids silently reusing whoever is already logged in
        # on a shared machine.
        "prompt": "select_account",
    }
    return AuthorizationRequest(
        url=f"{AUTH_ENDPOINT}?{urlencode(query)}",
        flow_cookie=sign_value(payload, ttl_seconds=FLOW_TTL_SECONDS),
    )


def read_flow(flow_cookie: str | None, state: str | None) -> dict[str, str]:
    """Validate the callback against the cookie we set when we started.

    Rejecting here is the whole point: a callback that cannot prove it belongs
    to a handshake *this browser* began is someone else's login attempt.
    """
    if not flow_cookie or not state:
        raise ValidationError("This sign-in link is incomplete. Start again from the login page.")
    raw = verify_signed_value(flow_cookie, max_age_seconds=FLOW_TTL_SECONDS)
    if raw is None:
        raise ValidationError("This sign-in link has expired. Start again from the login page.")
    flow = json.loads(raw)
    if not secrets.compare_digest(str(flow.get("state", "")), state):
        logger.warning("oauth_state_mismatch")
        raise ValidationError(
            "This sign-in could not be verified. Start again from the login page."
        )
    return flow


async def exchange_and_verify(code: str, verifier: str) -> dict[str, Any]:
    """Trade the code for an ID token and verify it. Returns the claims."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            token_response.raise_for_status()
            id_token = token_response.json().get("id_token")
            if not id_token:
                raise UpstreamUnavailableError("Google did not return an identity token.")
            jwks = (await client.get(JWKS_ENDPOINT)).json()
    except httpx.HTTPError as exc:
        logger.warning("oauth_exchange_failed", error=str(exc))
        raise UpstreamUnavailableError("Could not complete sign-in with Google.") from exc

    return _verify_id_token(id_token, jwks)


def _verify_id_token(id_token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    """Verify signature, issuer, audience and expiry.

    Verified rather than merely decoded: an unverified ID token is a
    user-supplied JSON blob, and treating one as identity means anyone can
    claim to be anyone.
    """
    import jwt

    try:
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key_data is None:
            raise UpstreamUnavailableError("Google's signing key was not recognised.")
        key = jwt.PyJWK.from_dict(key_data).key
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            # PyJWT applies **no leeway** unless asked, so a clock one second
            # behind Google's rejects a perfectly good token with "not yet
            # valid (iat)" -- which is what happened here the first time this
            # ran. Every OIDC library allows for skew for this reason, and
            # RFC 7519 explicitly permits it. A minute is small enough that a
            # genuinely expired token is still refused, and large enough that a
            # host whose clock drifts does not silently lose sign-in.
            leeway=CLOCK_SKEW_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("oauth_id_token_invalid", error=str(exc))
        raise ValidationError("Google's response could not be verified.") from exc

    if claims.get("iss") not in ISSUERS:
        raise ValidationError("Google's response could not be verified.")
    return claims


async def resolve_user(db: AsyncSession, claims: dict[str, Any]) -> tuple[User, OrgMember]:
    """Find or create the account behind these claims. Never commits."""
    subject = str(claims["sub"])
    email = (claims.get("email") or "").lower() or None
    email_verified = bool(claims.get("email_verified"))

    link = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == PROVIDER, OAuthAccount.subject == subject
            )
        )
    ).scalars().one_or_none()

    if link is not None:
        user = await db.get(User, link.user_id)
        if user is None or not user.is_active:
            raise ValidationError("This account is no longer active.")
        link.last_login_at = datetime.now(UTC)
        link.account_email = email
        link.email_verified = email_verified
        return user, await _membership_for(db, user)

    user = None
    if email and email_verified:
        # Linking to an existing password account is only safe because the
        # provider asserts the address is verified. Without that claim this
        # branch is an account-takeover primitive, so it is gated, not assumed.
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().one_or_none()
    elif email:
        logger.warning("oauth_unverified_email_not_linked", subject=subject)

    if user is None:
        if not email:
            raise ValidationError("Google did not share an email address for this account.")
        if not email_verified:
            raise ValidationError(
                "Google has not verified that email address, so it cannot be used to sign in."
            )
        user = await _create_user(db, email=email, claims=claims)

    db.add(
        OAuthAccount(
            user_id=user.id,
            provider=PROVIDER,
            subject=subject,
            account_email=email,
            email_verified=email_verified,
            last_login_at=datetime.now(UTC),
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        # Two first sign-ins raced. The constraint picked a winner; read it
        # back rather than guessing which one we were.
        await db.rollback()
        winner = (
            await db.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider == PROVIDER, OAuthAccount.subject == subject
                )
            )
        ).scalars().one_or_none()
        if winner is None:
            raise
        logger.info("oauth_link_race_resolved", subject=subject)
        existing = await db.get(User, winner.user_id)
        if existing is None:
            raise ValidationError("This account is no longer active.") from exc
        return existing, await _membership_for(db, existing)

    return user, await _membership_for(db, user)


async def _create_user(db: AsyncSession, *, email: str, claims: dict[str, Any]) -> User:
    """A new account, with no password at all.

    ``password_hash`` is nullable, so a Google-only user simply has none --
    rather than a random one they can never use and we must still store. If
    they later want a password, that is a set-password flow, not a reset.
    """
    display_name = (claims.get("name") or email.split("@")[0]).strip()[:160]
    user = User(
        email=email,
        password_hash=None,
        display_name=display_name,
        # Google verified it; making them verify it again teaches nothing.
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValidationError("An account with that email already exists.") from exc

    organization = Organization(
        name=f"{user.display_name}'s workspace",
        slug=f"u-{user.id.hex[:12]}",
        is_personal=True,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrgMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER.value)
    )
    await db.flush()
    logger.info("user_registered_via_oauth", user_id=str(user.id), provider=PROVIDER)
    return user


async def _membership_for(db: AsyncSession, user: User) -> OrgMember:
    membership = (
        await db.execute(
            select(OrgMember).where(OrgMember.user_id == user.id).limit(1)
        )
    ).scalars().one_or_none()
    if membership is None:
        raise ValidationError("This account has no workspace. Contact support.")
    return membership


def safe_next(candidate: str | None) -> str:
    """Only ever redirect within this app.

    ``//evil.example`` is a protocol-relative URL that browsers happily follow
    off-site, so a leading-slash check alone is not enough.
    """
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return "/dashboard"
    return candidate


def new_state_id() -> str:
    return uuid.uuid4().hex
