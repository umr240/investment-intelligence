"""Record what each deep dive read, and flag dives whose inputs were superseded.

Additive: five nullable columns on deepdive_runs (DEC-46). Existing dives keep
NULL provenance; a refresh that re-reads a ticker's filings flags them stale.

Revision ID: 0004_dive_provenance
Revises: 0003_fundamentals_fetched_at
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_dive_provenance"
down_revision = "0003_fundamentals_fetched_at"
branch_labels = None
depends_on = None

_COLUMNS = (
    sa.Column("parser_version", sa.Integer(), nullable=True),
    sa.Column("scorecard_view_json", sa.Text(), nullable=True),
    sa.Column("scorecard_view_sha256", sa.Text(), nullable=True),
    sa.Column("stale_reason", sa.Text(), nullable=True),
    sa.Column("stale_at", sa.DateTime(), nullable=True),
)


def upgrade() -> None:
    with op.batch_alter_table("deepdive_runs") as batch:
        for col in _COLUMNS:
            batch.add_column(col)


def downgrade() -> None:
    """Loses every stale flag, so withheld narratives become servable again. Back up first."""
    with op.batch_alter_table("deepdive_runs") as batch:
        for col in reversed(_COLUMNS):
            batch.drop_column(col.name)
