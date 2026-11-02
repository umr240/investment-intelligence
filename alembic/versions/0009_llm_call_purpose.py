"""Mark eval calls in llm_calls (ADR-047 §2.7 item 3).

Additive: one nullable column; existing rows are real use (NULL).

Revision ID: 0009_llm_call_purpose
Revises: 0008_data_contract_runs
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_llm_call_purpose"
down_revision = "0008_data_contract_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("purpose", sa.Text(), nullable=True))


def downgrade() -> None:
    """Loses which calls were evals. Back up first."""
    with op.batch_alter_table("llm_calls") as batch:
        batch.drop_column("purpose")
