"""Give the weekly-price task its own freshness column.

Additive: one nullable column. It shared latest_close_at with the daily price
task, which marked every ticker fresh first.

Revision ID: 0002_weekly_prices_fetched_at
Revises: 0001_baseline
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_weekly_prices_fetched_at"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("weekly_prices_fetched_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("weekly_prices_fetched_at")
