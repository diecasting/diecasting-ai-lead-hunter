"""Phase 15.1.1: Conversion Signal Foundation

Revision ID: 0031_phase15_conversion_signal
Revises: 0030_phase14_contact_ranking
Create Date: 2026-08-10

Phase 15.1.1 adds the ``conversion_signals`` table — the single latest
conversion-intelligence snapshot per lead. It starts with the deterministic
intent score (Phase 15.1.2) and will be extended in place by later phases
(15.1.3 temperature, 15.1.4 next-action) without a schema rewrite.

  * ``lead_id``          -- FK company_leads.id, SET NULL (analytics survive
                           lead deletion)
  * ``intent_score``     -- signed -100..100 intent score (indexed)
  * ``dominant_intent``  -- strongest driving intent class (or NULL)
  * ``signal_sources``   -- JSON-encoded provenance (Text, portable SQLite/PG)
  * ``computed_at``      -- timestamp of the latest computation (indexed)

Purely additive, single head. No existing table is modified.
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_phase15_conversion_signal"
down_revision = "0030_phase14_contact_ranking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversion_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("intent_score", sa.Integer(), nullable=True),
        sa.Column("dominant_intent", sa.String(length=40), nullable=True),
        sa.Column("signal_sources", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversion_signals_lead_id", "conversion_signals", ["lead_id"]
    )
    op.create_index(
        "ix_conversion_signals_intent_score", "conversion_signals", ["intent_score"]
    )
    op.create_index(
        "ix_conversion_signals_computed_at", "conversion_signals", ["computed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversion_signals_computed_at", table_name="conversion_signals")
    op.drop_index("ix_conversion_signals_intent_score", table_name="conversion_signals")
    op.drop_index("ix_conversion_signals_lead_id", table_name="conversion_signals")
    op.drop_table("conversion_signals")
