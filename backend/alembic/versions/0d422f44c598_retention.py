"""Bring existing retention windows down to six months (G-009).

Revision ID: 0d422f44c598
Revises: 8681738c67a1
Create Date: 2026-08-08 07:34:33.739293

Autogenerate produced an empty migration and was right to: the defaults are
Python-side, so the *schema* did not change. But a default only applies to rows
inserted afterwards -- every organisation created before this keeps 365-day
media and 730-day transcript windows, and would go on keeping data the consent
screen now says is deleted after six months.

That is the whole point of the change, so it is a data migration, written by
hand. Only rows still on the old defaults are touched: anyone who deliberately
chose a different window keeps it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0d422f44c598"
down_revision: str | None = "8681738c67a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIX_MONTHS = 180
OLD_MEDIA = 365
OLD_TRANSCRIPT = 730


# Written out rather than generated from a column name. Bound parameters
# cannot carry an identifier, so a helper would have to interpolate the column
# -- and a migration is the last place to normalise building SQL from strings,
# even where the input is a constant three lines up.
_MEDIA = sa.text(
    "UPDATE organizations SET media_retention_days = :new WHERE media_retention_days = :old"
)
_TRANSCRIPT = sa.text(
    "UPDATE organizations SET transcript_retention_days = :new "
    "WHERE transcript_retention_days = :old"
)


def upgrade() -> None:
    op.execute(_MEDIA.bindparams(new=SIX_MONTHS, old=OLD_MEDIA))
    op.execute(_TRANSCRIPT.bindparams(new=SIX_MONTHS, old=OLD_TRANSCRIPT))


def downgrade() -> None:
    # Restores the previous windows for rows that look untouched. It cannot
    # restore data already deleted under the shorter one -- worth saying out
    # loud rather than implying reversibility.
    op.execute(_MEDIA.bindparams(new=OLD_MEDIA, old=SIX_MONTHS))
    op.execute(_TRANSCRIPT.bindparams(new=OLD_TRANSCRIPT, old=SIX_MONTHS))
