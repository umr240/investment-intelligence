"""Record a digest of the fundamentals each deep dive read (DEC-47).

Additive: one nullable column on deepdive_runs. Existing dives keep NULL, which
DEC-47 treats as "inputs unknown": their narratives stay withheld.

Revision ID: 0005_dive_inputs_digest
Revises: 0004_dive_provenance
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_dive_inputs_digest"
down_revision = "0004_dive_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deepdive_runs") as batch:
        batch.add_column(sa.Column("inputs_sha256", sa.Text(), nullable=True))


def downgrade() -> None:
    """Loses every recorded digest, so all dives become "inputs unknown". Back up first."""
    with op.batch_alter_table("deepdive_runs") as batch:
        batch.drop_column("inputs_sha256")
