"""Every environment example we ship must survive the settings validator.

G-013. `.env.example` set ``AUTH_COOKIE_SAMESITE=none`` alongside
``AUTH_COOKIE_SECURE=false`` -- a pair the app's own validator correctly
refuses, because browsers silently drop such a cookie. The README tells you to
copy that file and CI did exactly that, so the documented quick start and the
smoke job both died at import, before serving a request.

The validator was right; the example was wrong. Nothing checked the example,
which is the actual gap: a config file is code, and this is its test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _repo_root() -> Path:
    """Where the examples live, from inside or outside a container.

    The test container mounts only ``backend/`` at ``/app``, so walking up from
    this file lands at ``/`` and finds nothing -- which would make every
    parametrised case below vacuously skip. Compose mounts the repo root at
    ``/repo`` read-only for exactly this.
    """
    mounted = Path("/repo")
    if (mounted / ".env.example").exists():
        return mounted
    return Path(__file__).resolve().parents[3]


REPO_ROOT = _repo_root()
EXAMPLES = sorted(REPO_ROOT.glob(".env*.example"))


def _parse(path: Path) -> dict[str, str]:
    """Read an example the way a human copying it would.

    Deliberately not python-dotenv: this asserts the file is *literally*
    usable, including that no value depends on shell expansion.
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Trailing `# comment` on a value line, which dotenv also strips.
        value = value.split("#", 1)[0].strip() if " #" in value else value.strip()
        values[key.strip()] = value
    return values


def test_there_is_at_least_one_example() -> None:
    """A glob that matches nothing would make every test below vacuously pass."""
    assert EXAMPLES, f"no .env*.example found under {REPO_ROOT}"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_example_boots(path: Path) -> None:
    """Construct Settings from the example alone, as a fresh clone would."""
    values = {key: value for key, value in _parse(path).items() if value != ""}
    # The production example intentionally ships with secrets blank; filling
    # them here keeps the test about *combinations* rather than about the
    # placeholders being empty.
    if values.get("ENVIRONMENT") == "production":
        values.setdefault("JWT_SECRET", "a-real-secret-for-this-test-only")

    try:
        settings = Settings(**values)  # type: ignore[arg-type]
    except ValidationError as exc:
        pytest.fail(f"{path.name} cannot boot:\n{exc}")

    # The specific pair that broke it: a `none` cookie is only honoured when
    # Secure, so this combination authenticates nobody.
    if settings.auth_cookie_samesite == "none":
        assert settings.auth_cookie_secure, (
            f"{path.name}: SameSite=none requires Secure=true or the browser drops the cookie"
        )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_example_does_not_carry_a_real_secret(path: Path) -> None:
    """A committed example is public. Treat anything that looks live as a leak."""
    placeholders = ("change-me", "minioadmin", "interview", "your-", "example", "localhost")
    suspicious = {
        key: value
        for key, value in _parse(path).items()
        if any(marker in key for marker in ("SECRET", "KEY", "PASSWORD", "TOKEN"))
        and value
        # A bare number is a duration or a size, not a credential. Without this
        # the check trips on ACCESS_TOKEN_TTL_SECONDS and gets muted by whoever
        # hits it next -- a noisy guard is a disabled guard.
        and not value.isdigit()
        and not any(placeholder in value.lower() for placeholder in placeholders)
    }
    assert not suspicious, (
        f"{path.name} looks like it contains real credentials: {list(suspicious)}"
    )


def test_the_local_example_matches_the_compose_default() -> None:
    """Copying the example and running compose must agree on the cookie mode.

    They are set in two places, and a disagreement means the documented setup
    behaves differently from the one CI runs.
    """
    local = _parse(REPO_ROOT / ".env.example")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert local["AUTH_COOKIE_SAMESITE"] == "lax"
    assert "AUTH_COOKIE_SAMESITE: ${AUTH_COOKIE_SAMESITE:-lax}" in compose
