"""Phase 16.3: Intent Aggregation Layer — CompanyLead intent snapshot columns

Revision ID: 0039_phase16_intent_snapshot
Revises: 0038_phase16_signal_event
Create Date: 2026-08-11

Adds six nullable columns to ``company_leads`` holding the aggregated buying-
intent snapshot produced by :mod:`app.intent.aggregator` from the
``signal_events`` ledger (Phase 16.1 + 16.2):

  * ``buying_intent_score``  Integer 0-100  — blended strength of active signals.
  * ``timing_score``         Integer 0-100  — recency / freshness of the mix.
  * ``intent_temperature``   String(10)      — HOT/WARM/COOL/COLD/NONE bucket.
  * ``last_signal_at``       DateTime        — most recent active signal time.
  * ``intent_source_count``  Integer         — count of distinct contributing sources.
  * ``intent_sources``       Text(JSON)      — sorted distinct source identifiers.

All columns are nullable so the migration is non-destructive and the snapshot
can be populated incrementally by the recompute script. No existing column
(``lead_score``, ``sales_priority``, ``priority``, ``buying_signal`` ...) is
touched, and no Opportunity / contact / ranking logic changes.

SQLite compatible: only ``op.add_column`` is used (SQLite supports ADD COLUMN
for nullable columns without rewriting the table). Single Alembic head is
preserved (down_revision = 0038_phase16_signal_event).
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_phase16_intent_snapshot"
down_revision = "0038_phase16_signal_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_leads",
        sa.Column("buying_intent_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "company_leads",
        sa.Column("timing_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "company_leads",
        sa.Column("intent_temperature", sa.String(10), nullable=True),
    )
    op.add_column(
        "company_leads",
        sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "company_leads",
        sa.Column("intent_source_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "company_leads",
        sa.Column("intent_sources", sa.Text(), nullable=True),
    )

    # Indexes for common query/filter patterns (all on nullable columns; SQLite
    # stores NULLs in the index without issue).
    op.create_index(
        "ix_company_leads_buying_intent_score", "company_leads", ["buying_intent_score"]
    )
    op.create_index(
        "ix_company_leads_intent_temperature", "company_leads", ["intent_temperature"]
    )
    op.create_index(
        "ix_company_leads_last_signal_at", "company_leads", ["last_signal_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_company_leads_last_signal_at", table_name="company_leads")
    op.drop_index("ix_company_leads_intent_temperature", table_name="company_leads")
    op.drop_index("ix_company_leads_buying_intent_score", table_name="company_leads")
    op.drop_column("company_leads", "intent_sources")
    op.drop_column("company_leads", "intent_source_count")
    op.drop_column("company_leads", "last_signal_at")
    op.drop_column("company_leads", "intent_temperature")
    op.drop_column("company_leads", "timing_score")
    op.drop_column("company_leads", "buying_intent_score")
