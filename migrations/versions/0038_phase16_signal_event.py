"""Phase 16.1: Intent Event Foundation — signal_events table

Revision ID: 0038_phase16_signal_event
Revises: 0037_phase15_opportunity_attribution
Create Date: 2026-08-10

Creates the ``signal_events`` ledger table that underpins the Buying Intent
Intelligence Engine. Each row is one timestamped, source-attributed, *raw*
buying-intent observation about a CompanyLead / Opportunity / Contact.

  * Three nullable SET NULL FKs (company_id / opportunity_id / contact_id) so a
    signal can attach to any of the three entity types without orphaning rows
    when the underlying entity is deleted.
  * ``value`` is a SIGNED intent/strength number (-100..+100); ``confidence`` is
    unsigned 0..100.
  * ``dedup_key`` (SHA-1, unique) is the deterministic idempotent-ingest key.
  * ``expires_at`` + ``is_active`` implement a TTL soft-toggle.
  * ``metadata_json`` stores arbitrary JSON context.

SQLite compatible: the table is created with ``op.create_table`` (FKs are
allowed inside CREATE TABLE on SQLite), and no ALTER/add-column FK is used. FKs
use ``ondelete="SET NULL"``. Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa


revision = "0038_phase16_signal_event"
down_revision = "0037_phase15_opportunity_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("signal_type", sa.String(40), nullable=False),
        sa.Column("intent_category", sa.String(20), nullable=True),
        # SIGNED intent/strength in -100..+100 (negative = deterrent).
        sa.Column("value", sa.Integer(), nullable=True),
        # Unsigned 0..100 source-reliability.
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company_leads.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )

    # Query indexes (the unique constraint already covers dedup_key lookups).
    op.create_index("ix_signal_events_company_id", "signal_events", ["company_id"])
    op.create_index(
        "ix_signal_events_opportunity_id", "signal_events", ["opportunity_id"]
    )
    op.create_index("ix_signal_events_contact_id", "signal_events", ["contact_id"])
    op.create_index("ix_signal_events_source", "signal_events", ["source"])
    op.create_index("ix_signal_events_signal_type", "signal_events", ["signal_type"])
    op.create_index(
        "ix_signal_events_intent_category", "signal_events", ["intent_category"]
    )
    op.create_index("ix_signal_events_value", "signal_events", ["value"])
    op.create_index("ix_signal_events_detected_at", "signal_events", ["detected_at"])
    op.create_index("ix_signal_events_expires_at", "signal_events", ["expires_at"])
    op.create_index("ix_signal_events_is_active", "signal_events", ["is_active"])
    op.create_index("ix_signal_events_external_id", "signal_events", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_signal_events_external_id", table_name="signal_events")
    op.drop_index("ix_signal_events_is_active", table_name="signal_events")
    op.drop_index("ix_signal_events_expires_at", table_name="signal_events")
    op.drop_index("ix_signal_events_detected_at", table_name="signal_events")
    op.drop_index("ix_signal_events_value", table_name="signal_events")
    op.drop_index("ix_signal_events_intent_category", table_name="signal_events")
    op.drop_index("ix_signal_events_signal_type", table_name="signal_events")
    op.drop_index("ix_signal_events_source", table_name="signal_events")
    op.drop_index("ix_signal_events_contact_id", table_name="signal_events")
    op.drop_index("ix_signal_events_opportunity_id", table_name="signal_events")
    op.drop_index("ix_signal_events_company_id", table_name="signal_events")
    op.drop_table("signal_events")
