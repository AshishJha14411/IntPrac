"""Per-user spend cap (NFR-C5).

Costs come out of a personal wallet, so this is a **design constraint, not a
dashboard metric**. The cap degrades gracefully -- it refuses to start a *new*
session rather than interrupting one in progress, because the failure mode we
are avoiding is a surprise bill, not a slightly shorter month.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import SpendCapExceededError
from app.core.logging import get_logger
from app.models.ops import UsageCost

logger = get_logger(__name__)


async def month_to_date_usd(db: AsyncSession, user_id: uuid.UUID) -> float:
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(UsageCost.usd), 0.0)).where(
                UsageCost.user_id == user_id, UsageCost.created_at >= start
            )
        )
    ).scalar_one()
    return float(total)


async def assert_within_cap(db: AsyncSession, user_id: uuid.UUID) -> float:
    """Refuse a new session once the month's budget is gone -- if one is set.

    Disabled by default (``MONTHLY_USD_CAP_PER_USER=0``). Blocking a candidate
    mid-practice with a budget message is a dead end they cannot act on, and
    the cap protected the *operator's* wallet by spending the *user's* goodwill.
    Cost is still measured on every call; it just no longer gates.

    Kept rather than deleted, because the concern is real and the switch should
    exist for the day this is not funded out of one person's pocket.
    """
    spent = await month_to_date_usd(db, user_id)
    if settings.monthly_usd_cap_per_user > 0 and spent >= settings.monthly_usd_cap_per_user:
        logger.warning("spend_cap_reached", user_id=str(user_id), spent_usd=round(spent, 4))
        raise SpendCapExceededError(
            "You have reached this month's practice budget. "
            "Text-only mode stays available, and the cap resets next month.",
            spent_usd=round(spent, 4),
            cap_usd=settings.monthly_usd_cap_per_user,
        )
    return spent
