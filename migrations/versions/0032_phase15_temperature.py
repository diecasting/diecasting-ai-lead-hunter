"""Phase 15.1.3: Lead Temperature Engine

Revision ID: 0032_phase15_temperature
Revises: 0031_phase15_conversion_signal
Create Date: 2026-08-10

Phase 15.1.3 extends the existing ``conversion_signals`` table (introduced in
15.1.1 / migration 0031) with the deterministic lead-temperature outputs:

  * ``temperature_score``   -- 0..100 composite heat score (indexed)
  * ``temperature_label``   -- cold / warm / hot (indexed)
  * ``temperature_reason``  -- human-readable component breakdown (Text)

Purely additive, single head. No existing column or table is modified, and the
downgrade drops only these three columns.
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_phase15_temperature"
down_revision = "0031_phase15_conversion_signal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversion_signals",
        sa.Column("temperature_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "conversion_signals",
        sa.Column("temperature_label", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "conversion_signals",
        sa.Column("temperature_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_conversion_signals_temperature_score",
        "conversion_signals",
        ["temperature_score"],
    )
    op.create_index(
        "ix_conversion_signals_temperature_label",
        "conversion_signals",
        ["temperature_label"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversion_signals_temperature_label", table_name="conversion_signals"
    )
    op.drop_index(
        "ix_conversion_signals_temperature_score", table_name="conversion_signals"
    )
    op.drop_column("conversion_signals", "temperature_reason")
    op.drop_column("conversion_signals", "temperature_label")
    op.drop_column("conversion_signals", "temperature_score")
