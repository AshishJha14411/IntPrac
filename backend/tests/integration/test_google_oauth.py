"""Google sign-in, focused on the three things that can go badly wrong.

This flow was ported from the v1 project, which shipped without ``state`` and
linked accounts on an unverified email. Both are the kind of hole that a green
happy-path test never touches, so these tests are the divergences written down
as assertions rather than as comments.

The network is not involved: ``exchange_and_verify`` is the seam, and stubbing
it lets every branch after "Google said who this is" be tested for real,
against the real database.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ValidationError
from app.core.security import sign_value
from app.models.identity import User
from app.models.oauth import OAuthAccount
from app.services import oauth

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix
CALLBACK = f"{PREFIX}/auth/google/callback"
FLOW_PATH = f"{PREFIX}/auth/google"


def claims(sub: str, email: str, *, verified: bool = True, name: str = "Ada") -> dict[str, Any]:
    return {"sub": sub, "email": email, "email_verified": verified, "name": name}


@pytest.fixture()
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Google client at all.

    Set explicitly rather than inherited: once a real GOOGLE_CLIENT_ID exists
    in a developer's gitignored .env, an ambient default silently flips these
    tests to asserting the opposite of what they are named for.
    """
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)


@pytest.fixture()
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_base_url", "http://localhost:3000")


def _begin(client: TestClient, next_path: str = "/dashboard") -> str:
    """Start a handshake and return the ``state`` Google would echo back."""
    response = client.get(
        f"{PREFIX}/auth/google/login", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 303
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"], "PKCE, not a bare code flow"
    assert query["code_challenge"], "a challenge must be sent or PKCE is decorative"
    return query["state"][0]


def _stub_google(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    async def fake_exchange(code: str, verifier: str) -> dict[str, Any]:
        assert verifier, "the PKCE verifier must reach the token exchange"
        return payload

    monkeypatch.setattr(oauth, "exchange_and_verify", fake_exchange)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_first_sign_in_creates_an_account_with_no_password(
    client: TestClient, db: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _begin(client)
    _stub_google(monkeypatch, claims("google-sub-1", "ada@example.com"))

    response = client.get(
        CALLBACK, params={"code": "auth-code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/dashboard"
    # Signed in on arrival: no interstitial page needed to finish the job.
    assert "interview_access" in response.cookies
    assert "interview_refresh" in response.cookies

    user = db.query(User).filter(User.email == "ada@example.com").one()
    assert user.password_hash is None, "a Google-only account needs no unusable password"
    assert user.email_verified_at is not None, "Google verified it; don't ask twice"
    assert user.memberships, "every user needs a workspace or nothing else works"


def test_returning_sign_in_reuses_the_link_and_makes_no_second_account(
    client: TestClient, db: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = claims("google-sub-2", "grace@example.com")
    for _ in range(2):
        state = _begin(client)
        _stub_google(monkeypatch, payload)
        client.get(CALLBACK, params={"code": "c", "state": state}, follow_redirects=False)

    assert db.query(User).filter(User.email == "grace@example.com").count() == 1
    assert db.query(OAuthAccount).filter(OAuthAccount.subject == "google-sub-2").count() == 1


def test_identity_follows_the_subject_not_the_email(
    client: TestClient, db: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed email must not create a second account, or lose the first.

    Emails get changed and reassigned; the OIDC ``sub`` does not. Keying on the
    address is how an old one silently hands over an account.
    """
    state = _begin(client)
    _stub_google(monkeypatch, claims("google-sub-3", "old@example.com"))
    client.get(CALLBACK, params={"code": "c", "state": state}, follow_redirects=False)
    original = db.query(User).filter(User.email == "old@example.com").one().id

    state = _begin(client)
    _stub_google(monkeypatch, claims("google-sub-3", "new@example.com"))
    client.get(CALLBACK, params={"code": "c", "state": state}, follow_redirects=False)

    link = db.query(OAuthAccount).filter(OAuthAccount.subject == "google-sub-3").one()
    assert link.user_id == original, "same person, same account"
    assert link.account_email == "new@example.com", "but we record what they used"


# ---------------------------------------------------------------------------
# The two holes in the flow this was ported from
# ---------------------------------------------------------------------------
def test_a_callback_without_state_is_refused(
    client: TestClient, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Login CSRF.

    With no ``state`` check, an attacker completes a handshake for *their* own
    Google account, then makes your browser follow the resulting callback URL.
    You are silently signed into their account, and every interview you take
    next is in their history. The v1 flow sends no state at all.
    """
    _stub_google(monkeypatch, claims("attacker-sub", "attacker@example.com"))
    response = client.get(CALLBACK, params={"code": "stolen"}, follow_redirects=False)

    assert response.status_code == 303
    assert "error=failed" in response.headers["location"]
    assert "interview_access" not in response.cookies


def test_a_forged_state_cookie_is_refused(
    client: TestClient, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cookie is signed, so a hand-rolled one cannot pass."""
    _stub_google(monkeypatch, claims("attacker-sub", "attacker@example.com"))
    client.cookies.set(
        "interview_oauth_flow", '{"state":"abc","verifier":"v","next":"/"}', path=FLOW_PATH
    )
    response = client.get(
        CALLBACK, params={"code": "c", "state": "abc"}, follow_redirects=False
    )
    client.cookies.clear()

    assert "error=failed" in response.headers["location"]
    assert "interview_access" not in response.cookies


def test_state_from_one_handshake_cannot_finish_another(
    client: TestClient, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A validly-signed cookie still has to match *this* callback's state."""
    _begin(client)  # the cookie now in the jar belongs to this handshake
    _stub_google(monkeypatch, claims("attacker-sub", "attacker@example.com"))

    response = client.get(
        CALLBACK, params={"code": "c", "state": "some-other-state"}, follow_redirects=False
    )
    assert "error=failed" in response.headers["location"]
    assert "interview_access" not in response.cookies


def test_an_unverified_email_cannot_take_over_a_password_account(
    client: TestClient, db: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Account takeover.

    Linking on email alone means anyone who can get a provider to assert an
    address they do not own inherits that account -- password and all. So the
    link is gated on ``email_verified``, and without it we refuse rather than
    quietly creating a second account on the same address.
    """
    client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": "victim@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Victim",
        },
    )
    client.cookies.clear()
    victim = db.query(User).filter(User.email == "victim@example.com").one()
    original_hash = victim.password_hash

    state = _begin(client)
    _stub_google(monkeypatch, claims("attacker-sub", "victim@example.com", verified=False))
    response = client.get(
        CALLBACK, params={"code": "c", "state": state}, follow_redirects=False
    )

    assert "error=failed" in response.headers["location"]
    assert "interview_access" not in response.cookies
    assert db.query(OAuthAccount).filter(OAuthAccount.subject == "attacker-sub").count() == 0
    db.refresh(victim)
    assert victim.password_hash == original_hash, "the password account is untouched"


def test_a_verified_email_does_link_to_the_existing_account(
    client: TestClient, db: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the gate: verified means the same person."""
    client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": "both@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Both",
        },
    )
    client.cookies.clear()
    existing = db.query(User).filter(User.email == "both@example.com").one().id

    state = _begin(client)
    _stub_google(monkeypatch, claims("google-sub-4", "both@example.com", verified=True))
    client.get(CALLBACK, params={"code": "c", "state": state}, follow_redirects=False)

    link = db.query(OAuthAccount).filter(OAuthAccount.subject == "google-sub-4").one()
    assert link.user_id == existing, "one person, one account, two ways in"
    assert db.query(User).filter(User.email == "both@example.com").count() == 1


# ---------------------------------------------------------------------------
# Redirect safety and configuration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("/report/abc", "/report/abc"),
        ("//evil.example", "/dashboard"),  # protocol-relative: browsers leave the site
        ("https://evil.example", "/dashboard"),
        ("", "/dashboard"),
        (None, "/dashboard"),
    ],
)
def test_the_landing_path_cannot_leave_the_app(candidate: str | None, expected: str) -> None:
    assert oauth.safe_next(candidate) == expected


def test_an_expired_handshake_is_refused(
    client: TestClient, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signature is still valid; the clock has simply run out."""
    import json

    stale = sign_value(
        json.dumps({"state": "s", "verifier": "v", "next": "/"}), ttl_seconds=-1
    )
    _stub_google(monkeypatch, claims("sub", "x@example.com"))
    client.cookies.set("interview_oauth_flow", stale, path=FLOW_PATH)
    response = client.get(CALLBACK, params={"code": "c", "state": "s"}, follow_redirects=False)
    client.cookies.clear()

    assert "error=failed" in response.headers["location"]


def test_the_routes_are_absent_when_no_client_is_configured(
    client: TestClient, unconfigured: None
) -> None:
    """A button leading to a Google error page is worse than no button."""
    assert client.get(f"{PREFIX}/auth/google/status").json()["enabled"] is False
    assert (
        client.get(f"{PREFIX}/auth/google/login", follow_redirects=False).status_code == 404
    )


def test_the_missing_config_is_explained_outside_production_only(
    client: TestClient, unconfigured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hiding the button is right for users and baffling for the operator.

    So the reason is shown outside production and never inside it -- a public
    login page that narrates its own configuration is telling an attacker which
    doors were never fitted.
    """
    body = client.get(f"{PREFIX}/auth/google/status").json()
    assert "GOOGLE_CLIENT_ID" in body["hint"]
    assert settings.google_redirect_uri in body["hint"], "say which URI to register"

    monkeypatch.setattr(settings, "environment", "production")
    assert "hint" not in client.get(f"{PREFIX}/auth/google/status").json()


def test_declining_consent_is_not_an_error(client: TestClient, configured: None) -> None:
    """Pressing cancel is a choice, not a failure. Say so differently."""
    response = client.get(
        CALLBACK, params={"error": "access_denied"}, follow_redirects=False
    )
    assert "error=cancelled" in response.headers["location"]


def test_the_flow_cookie_is_scoped_and_httponly(client: TestClient, configured: None) -> None:
    """It carries the PKCE verifier, so JavaScript must never see it."""
    response = client.get(f"{PREFIX}/auth/google/login", follow_redirects=False)
    header = response.headers["set-cookie"]
    assert "interview_oauth_flow=" in header
    assert "HttpOnly" in header
    # `lax`, never `strict`: Google's callback is a cross-site top-level
    # navigation, which `strict` drops -- breaking sign-in with no error.
    assert "SameSite=lax" in header.lower().replace("samesite=lax", "SameSite=lax")
    assert f"Path={FLOW_PATH}" in header


def test_unique_constraint_is_the_arbiter_for_the_link() -> None:
    """Never check-then-insert (Appendix D.1 #2)."""
    constraint = next(
        c for c in OAuthAccount.__table__.constraints if getattr(c, "name", "") ==
        "uq_oauth_provider_subject"
    )
    assert {column.name for column in constraint.columns} == {"provider", "subject"}


def test_no_provider_tokens_are_stored() -> None:
    """We never call Google on the user's behalf, so holding a token is pure risk."""
    columns = set(OAuthAccount.__table__.columns.keys())
    assert not columns & {"access_token", "refresh_token", "id_token"}
    assert uuid.UUID  # keeps the import meaningful for the type checker


# ---------------------------------------------------------------------------
# ID token verification
# ---------------------------------------------------------------------------
def _signed_token(**overrides: Any) -> tuple[str, dict[str, Any]]:
    """Mint an RS256 token and the JWKS that verifies it."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": settings.google_client_id,
        "sub": "sub-123",
        "email": "clock@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    token = jwt.encode(payload, private, algorithm="RS256", headers={"kid": "test-kid"})
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "test-kid", "alg": "RS256", "use": "sig"})
    return token, {"keys": [jwk]}


def test_a_token_issued_a_second_in_our_future_still_verifies(configured: None) -> None:
    """The bug that broke the first real sign-in.

    PyJWT applies no leeway by default, so a container clock one second behind
    Google's rejects a valid token with "The token is not yet valid (iat)".
    Clocks drift; sign-in must not.
    """
    token, jwks = _signed_token(iat=int(datetime.now(UTC).timestamp()) + 5)
    assert oauth._verify_id_token(token, jwks)["sub"] == "sub-123"


def test_leeway_does_not_excuse_a_genuinely_expired_token(configured: None) -> None:
    """Tolerating skew must not become tolerating expiry."""
    past = int(datetime.now(UTC).timestamp()) - (oauth.CLOCK_SKEW_LEEWAY_SECONDS + 600)
    token, jwks = _signed_token(iat=past, exp=past + 60)
    with pytest.raises(ValidationError):
        oauth._verify_id_token(token, jwks)


def test_a_token_for_another_audience_is_refused(configured: None) -> None:
    """Without this, any Google app's token signs you in here."""
    token, jwks = _signed_token(aud="some-other-app.apps.googleusercontent.com")
    with pytest.raises(ValidationError):
        oauth._verify_id_token(token, jwks)


def test_a_token_from_another_issuer_is_refused(configured: None) -> None:
    token, jwks = _signed_token(iss="https://evil.example")
    with pytest.raises(ValidationError):
        oauth._verify_id_token(token, jwks)


def test_a_token_signed_by_the_wrong_key_is_refused(configured: None) -> None:
    """The signature is the whole basis for believing any of the claims."""
    token, _ = _signed_token()
    _, other_jwks = _signed_token()  # a different keypair, same kid
    with pytest.raises(ValidationError):
        oauth._verify_id_token(token, other_jwks)
