"""Phase 2.5: CRM pipeline — lead_status fields + outreach_events table

Revision ID: 0004_phase25_crm
Revises: 0003_phase24_outreach
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_phase25_crm"
down_revision = "0003_phase24_outreach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- New columns on company_leads ----------------------------------------
    op.add_column(
        "company_leads",
        sa.Column(
            "lead_status",
            sa.String(length=20),
            nullable=False,
            server_default="new",
        ),
    )
    op.add_column(
        "company_leads", sa.Column("last_activity_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "company_leads", sa.Column("next_followup_date", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_company_leads_lead_status", "company_leads", ["lead_status"])

    # --- outreach_messages: sending tracking columns ------------------------
    op.add_column(
        "outreach_messages", sa.Column("sent_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "outreach_messages", sa.Column("sender", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "outreach_messages", sa.Column("recipient", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "outreach_messages",
        sa.Column("is_followup", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outreach_messages",
        sa.Column("followup_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_outreach_messages_is_followup", "outreach_messages", ["is_followup"])

    # --- outreach_events table -----------------------------------------------
    op.create_table(
        "outreach_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["outreach_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_events_id", "outreach_events", ["id"])
    op.create_index("ix_outreach_events_lead_id", "outreach_events", ["lead_id"])
    op.create_index("ix_outreach_events_message_id", "outreach_events", ["message_id"])
    op.create_index("ix_outreach_events_event_type", "outreach_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_outreach_events_event_type", table_name="outreach_events")
    op.drop_index("ix_outreach_events_message_id", table_name="outreach_events")
    op.drop_index("ix_outreach_events_lead_id", table_name="outreach_events")
    op.drop_index("ix_outreach_events_id", table_name="outreach_events")
    op.drop_table("outreach_events")

    op.drop_index("ix_outreach_messages_is_followup", table_name="outreach_messages")
    op.drop_column("outreach_messages", "followup_seq")
    op.drop_column("outreach_messages", "is_followup")
    op.drop_column("outreach_messages", "recipient")
    op.drop_column("outreach_messages", "sender")
    op.drop_column("outreach_messages", "sent_time")

    op.drop_index("ix_company_leads_lead_status", table_name="company_leads")
    op.drop_column("company_leads", "next_followup_date")
    op.drop_column("company_leads", "last_activity_time")
    op.drop_column("company_leads", "lead_status")
