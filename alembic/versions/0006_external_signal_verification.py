"""Record the model's band and value, and the verifier's outcome, per external signal (ADR-057).

Additive: three nullable columns on external_signals. Existing rows keep NULL
until scripts/verify_external_signals.py checks them.

Revision ID: 0006_external_signal_verification
Revises: 0005_dive_inputs_digest
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_external_signal_verification"
down_revision = "0005_dive_inputs_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("external_signals") as batch:
        batch.add_column(sa.Column("model_confidence", sa.Text(), nullable=True))
        batch.add_column(sa.Column("model_value_numeric", sa.Float(), nullable=True))
        batch.add_column(sa.Column("verification", sa.Text(), nullable=True))


def downgrade() -> None:
    """Loses every recorded verification and the model's original values. Back up first."""
    with op.batch_alter_table("external_signals") as batch:
        batch.drop_column("verification")
        batch.drop_column("model_value_numeric")
        batch.drop_column("model_confidence")
