"""Phase 15.4.3: Opportunity attribution layer

Revision ID: 0037_phase15_opportunity_attribution
Revises: 0036_phase15_recommendation_closure
Create Date: 2026-08-10

Adds the Conversion Intelligence attribution bridge to the ``opportunities``
table so a deal can be traced back to the signal that triggered it, and carries
the AI-derived temperature / intent / probability for analytics:

  * opportunities.conversion_signal_id -> conversion_signals.id (SET NULL, index)
  * opportunities.ai_temperature_score  Integer, nullable
  * opportunities.ai_intent_score       Integer, nullable
  * opportunities.ai_probability        Integer, nullable
  * opportunities.probability_source     String(20), nullable

All FKs are ``SET NULL`` so deleting the underlying signal never orphans a deal.
Purely additive, single head. Downgrade drops the columns + index.
"""
from alembic import op
import sqlalchemy as sa


revision = "0037_phase15_opportunity_attribution"
down_revision = "0036_phase15_recommendation_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(
            sa.Column("conversion_signal_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_temperature_score", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_intent_score", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_probability", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("probability_source", sa.String(20), nullable=True)
        )
        batch_op.create_index(
            "ix_opportunities_conversion_signal_id", ["conversion_signal_id"]
        )
        batch_op.create_foreign_key(
            "fk_opportunities_conversion_signal_id",
            "conversion_signals",
            ["conversion_signal_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_constraint(
            "fk_opportunities_conversion_signal_id", type_="foreignkey"
        )
        batch_op.drop_index("ix_opportunities_conversion_signal_id")
        batch_op.drop_column("probability_source")
        batch_op.drop_column("ai_probability")
        batch_op.drop_column("ai_intent_score")
        batch_op.drop_column("ai_temperature_score")
        batch_op.drop_column("conversion_signal_id")
