"""Application settings.

One source of truth, validated at import time. A misconfigured environment
should fail loudly at boot, not at the first request that happens to need it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- app ---
    environment: Environment = "development"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    api_v1_prefix: str = "/api/v1"
    # `NoDecode` stops pydantic-settings from JSON-parsing this before our
    # validator runs -- without it, CORS_ORIGINS=http://localhost:3000 fails at
    # import time because it isn't valid JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- database ---
    # async engine drives the request path; the sync engine exists for Celery
    # workers and seed scripts (Appendix D.4: dual engines on purpose).
    database_url: str = "postgresql+asyncpg://interview:interview@localhost:5432/interview"
    sync_database_url: str = "postgresql+psycopg://interview:interview@localhost:5432/interview"
    migration_database_url: str = "postgresql+psycopg://interview:interview@localhost:5432/interview"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- redis / queues ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- dispatch mode (ADR 010) ---
    #: Run tasks inline in the web process instead of shipping them to a broker.
    #: A Celery worker is a *polling* consumer: it has no HTTP surface, so a
    #: scale-to-zero host has nothing to scale it up on and it must be pinned to
    #: one always-on instance. That is a CPU billed 24/7 for a system that is
    #: idle most of the day. Named after Celery's own setting so it is greppable.
    celery_task_always_eager: bool = False
    #: Wall-clock ceiling on how long one request may spend draining the outbox.
    #: Checked *before* starting each event, so a request absorbs at most one
    #: over-budget task; the rest stay pending for the next request to pick up.
    #: 0 disables the post-commit drain entirely -- set that when a real worker
    #: is running and you still want eager mode for some other reason.
    inline_drain_budget_seconds: float = 10.0
    inline_drain_batch_size: int = 10

    # --- object storage ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"  # noqa: S105
    s3_bucket_uploads: str = "interview-uploads"
    s3_presign_expiry_seconds: int = 900
    max_upload_bytes: int = 10 * 1024 * 1024  # FR-R1

    # --- auth ---
    jwt_secret: str = "dev-only-secret-do-not-use-in-production"  # noqa: S105
    jwt_algorithm: str = "HS256"
    #: Six hours. Was 15 minutes, which is the textbook number and was wrong
    #: here: a 45-minute interview spans it three times, and nothing renewed
    #: the token, so candidates were logged out mid-answer. The client now
    #: refreshes on a 401, but a long-lived access token means the common case
    #: never reaches that path at all.
    #:
    #: The trade is real and bounded: an access token cannot be revoked before
    #: it expires, so a stolen one is usable for up to six hours instead of
    #: fifteen minutes. Refresh-token rotation with reuse detection is what
    #: actually contains a compromised *session*, and that is unchanged.
    access_token_ttl_seconds: int = 6 * 3600
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    auth_cookie_secure: bool = False
    #: ``lax`` is right whenever the browser app and the API share a registrable
    #: domain (including localhost:3000 -> localhost:8080, where the port is not
    #: part of "site"). Split them across *different* domains -- the usual
    #: frontend-host + backend-host deploy -- and the pair is cross-site, a
    #: ``lax`` cookie is never sent on ``fetch``, and every authenticated
    #: request 401s. That deploy needs ``none``, which browsers only honour
    #: alongside ``Secure``. See the guardrail below.
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None

    # --- google sign-in (OIDC authorization code + PKCE) ---
    #: Unset => the button is not shown and the routes 404. A half-configured
    #: OAuth flow that renders a button leading to a Google error page is worse
    #: than no button.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    #: Must match the Authorised redirect URI in the Google Cloud console
    #: *exactly*, including scheme and trailing path. A mismatch is the single
    #: most common cause of `redirect_uri_mismatch`.
    google_redirect_uri: str = "http://localhost:8080/api/v1/auth/google/callback"
    #: Where the browser lands after the callback has set the cookies.
    frontend_base_url: str = "http://localhost:3000"

    # --- llm (Google Gemini; see app/llm/client.py for the adapter) ---
    gemini_api_key: str | None = None
    llm_enabled: bool = True
    #: Measured, then chosen. At `gemini-3.5-flash` real usage came out at
    #: $0.106 per session, and **86% of that was output tokens** -- almost all
    #: of it the model's own thinking, at $9.00 per million.
    #:
    #: `-lite` is $2.50 per million out and $0.30 in: 3.6x and 5x cheaper, on a
    #: task that is closed-book pattern matching against a rubric we supply,
    #: with a JSON schema constraining the answer. That is the shape of task a
    #: small model does well; the reasoning that costs money here was being
    #: spent re-deriving things the rubric already states.
    #:
    #: Set this back to `gemini-3.5-flash` if verdict quality visibly drops --
    #: it is one environment variable, and the invariance gate runs against the
    #: deterministic stub either way, so switching cannot move a score silently.
    llm_grader_model: str = "gemini-3.5-flash-lite"
    #: Reduction is classification against a closed taxonomy (§1.2) -- the
    #: output is a list of ids, not prose -- so it runs on the cheapest tier.
    #: Roughly 4x cheaper per output token than the grader, for easier work.
    #:
    #: ⚠ Both defaults are 3.x deliberately. The entire **2.5 family is retired
    #: for new API accounts** -- `gemini-2.5-flash` and `gemini-2.5-flash-lite`
    #: return 404 "no longer available to new users", *while still appearing in
    #: `models.list()`*. Listing a model is not permission to call it; verify a
    #: model by calling it.
    llm_reduction_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 2
    #: NFR-C5, **off by default**. A cap that refuses to start a session is a
    #: dead end for the candidate and tells them nothing they can act on, which
    #: is a bad trade for a practice product. Costs are still recorded per call
    #: (NFR-C1) -- what changed is that measuring spend no longer blocks anyone.
    #: Set a positive number to re-arm it; 0 disables.
    monthly_usd_cap_per_user: float = 0.0

    # --- voice (FR-V) ---
    #: FR-V4: below this, a segment is marked uncertain rather than presented as
    #: fact. The server owns the threshold so the judgement is consistent and a
    #: client cannot quietly launder its own low-confidence output as certain.
    stt_low_confidence_threshold: float = 0.6

    #: How many rubrics one planning request may generate. A cost and latency
    #: control: a session short by seventeen questions would otherwise make
    #: seventeen model calls before showing anything. Capped, the bank fills in
    #: over successive sessions and the next candidate on that topic pays
    #: nothing -- the same argument as NFR-C2, applied to questions.
    max_generations_per_plan: int = 3

    # --- interview defaults ---
    max_hints_per_question: int = 3
    max_followups_per_question: int = 2  # FR-E5b
    default_target_minutes: int = 20

    @model_validator(mode="before")
    @classmethod
    def _blank_means_default(cls, data: object) -> object:
        """An empty env var means "use the default below", not "".

        This closes a bug that quietly cost real money. The grader default here
        was changed to the cheaper model, but ``docker-compose.yml`` carried its
        own literal fallback -- and compose's ``${VAR:-literal}`` *always sets*
        the variable, so the code default was dead and every call kept going to
        the expensive one. The measured saving never shipped, and nothing said
        so: two sources of truth, and the wrong one won.

        Compose now passes an empty string when nobody has chosen. Deleting the
        key (rather than coercing it) is what makes pydantic fall back to the
        field default, so there is exactly one default and it lives here.
        """
        if isinstance(data, dict):
            for key in ("llm_grader_model", "llm_reduction_model"):
                for candidate in (key, key.upper()):
                    value = data.get(candidate)
                    if isinstance(value, str) and not value.strip():
                        data.pop(candidate)
        return data

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _production_guardrails(self) -> Settings:
        # Not production-only: every major browser silently *rejects* a
        # `SameSite=None` cookie that isn't `Secure`. Getting this wrong looks
        # like "login succeeds and then I'm logged out", with nothing in any
        # log, so it fails at boot instead.
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")
        if self.environment == "production":
            if self.jwt_secret.startswith("dev-only"):
                raise ValueError("JWT_SECRET must be set in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        if self.llm_enabled and self.environment != "test" and not self.gemini_api_key:
            # Not fatal: the app degrades to the stub adapter and says so loudly,
            # rather than failing every boot on a machine without a key.
            self.llm_enabled = False
        return self

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def workerless(self) -> bool:
        """True when no separate worker process is expected to exist."""
        return self.celery_task_always_eager

    @property
    def inline_dispatch_enabled(self) -> bool:
        """True when a successful request should drain the outbox itself."""
        return self.celery_task_always_eager and self.inline_drain_budget_seconds > 0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
