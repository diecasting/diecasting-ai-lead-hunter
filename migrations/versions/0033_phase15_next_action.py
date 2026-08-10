"""Phase 15.1.4: Next-Action Recommendation Engine

Revision ID: 0033_phase15_next_action
Revises: 0032_phase15_temperature
Create Date: 2026-08-10

Phase 15.1.4 extends the existing ``conversion_signals`` table (introduced in
15.1.1 / migration 0031) with the deterministic next-action recommendation:

  * ``next_action``         -- recommended CRM action (indexed, for filtering)
  * ``next_action_priority``-- high / medium / low
  * ``next_action_reason``  -- human-readable rationale (Text)

Purely additive, single head. No existing column or table is modified, and the
downgrade drops only these three columns.
"""
from alembic import op
import sqlalchemy as sa


revision = "0033_phase15_next_action"
down_revision = "0032_phase15_temperature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversion_signals",
        sa.Column("next_action", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "conversion_signals",
        sa.Column("next_action_priority", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "conversion_signals",
        sa.Column("next_action_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_conversion_signals_next_action",
        "conversion_signals",
        ["next_action"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversion_signals_next_action", table_name="conversion_signals"
    )
    op.drop_column("conversion_signals", "next_action_reason")
    op.drop_column("conversion_signals", "next_action_priority")
    op.drop_column("conversion_signals", "next_action")
