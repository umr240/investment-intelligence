"""Give FundamentalsTask its own freshness column.

Additive: one nullable column, initialised from roic_fetched_at so existing
rows keep their freshness. The task gated on roic_fetched_at, which is set only
when a ROIC is computable, so banks, REITs and filers without annuals were
re-read on every run.

Revision ID: 0003_fundamentals_fetched_at
Revises: 0002_weekly_prices_fetched_at
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_fundamentals_fetched_at"
down_revision = "0002_weekly_prices_fetched_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("fundamentals_fetched_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE companies SET fundamentals_fetched_at = roic_fetched_at")


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("fundamentals_fetched_at")
