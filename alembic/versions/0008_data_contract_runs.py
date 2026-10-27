"""One row per data contract result (ADR-044).

Additive: a new table; nothing existing changes.

Revision ID: 0008_data_contract_runs
Revises: 0007_llm_calls
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_data_contract_runs"
down_revision = "0007_llm_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_contract_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("failing", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("sample_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_data_contract_runs_contract_id", "data_contract_runs", ["contract_id"])
    op.create_index("ix_data_contract_runs_created_at", "data_contract_runs", ["created_at"])


def downgrade() -> None:
    """Loses every recorded contract result. Back up first."""
    op.drop_table("data_contract_runs")
