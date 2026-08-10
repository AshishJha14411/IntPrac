"""synthesised plans: competency origin, bank followups

Revision ID: 2888df892b1f
Revises: 740fe68c97f8
Create Date: 2026-08-10 19:01:38.952882

Two columns for plan synthesis, both backfilled rather than nullable.

Autogenerate produced them as ``nullable=False`` with no ``server_default``,
which cannot apply: there are already 129 taxonomy rows and 64 bank questions,
and Postgres has nothing to put in the new column for them. The defaults below
are what the existing rows actually mean -- everything in the bank today was
written by a human, and none of it carries follow-ups -- so this is a backfill
with the right value, not a placeholder.

The server defaults stay. They are the correct value for any row inserted
outside the ORM (a seed script, a manual fix), and dropping them would only
move the problem to whoever does that next.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2888df892b1f"
down_revision: str | None = "740fe68c97f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competency_taxonomy",
        sa.Column(
            "origin",
            sa.String(length=16),
            nullable=False,
            # Everything seeded from `content/taxonomy.py` is authored. Only
            # plan synthesis writes 'inferred'.
            server_default="authored",
        ),
    )
    op.add_column(
        "question_bank",
        sa.Column(
            "followups",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            # The authored banks have none and fall back to the concept's
            # signpost, which is hint content and discounts the candidate.
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "followups",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("session_questions", "followups")
    op.drop_column("question_bank", "followups")
    op.drop_column("competency_taxonomy", "origin")
