"""Federated sign-in links.

One row per (provider, provider's stable id for this person). The provider's
``sub`` is the identity, **not** the email: emails get reassigned, changed, and
in some tenancies recycled, so keying on one silently hands an old address's
account to whoever holds it next.

Note what is deliberately *not* stored: the provider's access and refresh
tokens. We ask for `openid email profile`, read the claims once at sign-in, and
never call Google on the user's behalf again -- so keeping those tokens would
be a credential we have no use for and would still have to protect (NFR-SEC).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.identity import User


class OAuthAccount(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        # The arbiter for "have we seen this person before" (Appendix D.1 #2).
        # Two concurrent first sign-ins race here and the loser is translated,
        # never pre-checked.
        UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The OIDC ``sub`` claim: stable for this person at this provider forever.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    #: What the provider said at the last sign-in, kept for support questions
    #: ("which Google account did I use?"). Never used to resolve identity.
    account_email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
