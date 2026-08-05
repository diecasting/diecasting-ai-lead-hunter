"""Phase 6 Stage 3: Reply Inbox Connector

Adds ``incoming_emails`` — one row per inbound reply pulled from the email
inbox, tracking its processing state, the matched lead / originating
outreach message, and the created reply analysis.

Revision ID: 0017_phase63_reply_inbox
Revises: 0016_phase62_reply_intelligence
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_phase63_reply_inbox"
down_revision = "0016_phase62_reply_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incoming_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "processed", sa.Boolean(), nullable=False, server_default="0"
        ),
        sa.Column("matched_lead_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("analysis_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["reply_analyses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["matched_lead_id"], ["company_leads.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["outreach_messages.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_incoming_emails_id", "incoming_emails", ["id"])
    op.create_index(
        "ix_incoming_emails_sender_email", "incoming_emails", ["sender_email"]
    )
    op.create_index(
        "ix_incoming_emails_processed", "incoming_emails", ["processed"]
    )
    op.create_index(
        "ix_incoming_emails_received_at", "incoming_emails", ["received_at"]
    )
    op.create_index(
        "ix_incoming_emails_matched_lead_id", "incoming_emails", ["matched_lead_id"]
    )
    op.create_index(
        "ix_incoming_emails_message_id", "incoming_emails", ["message_id"]
    )
    op.create_index(
        "ix_incoming_emails_analysis_id", "incoming_emails", ["analysis_id"]
    )
    op.create_index(
        "ix_incoming_emails_external_id", "incoming_emails", ["external_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_incoming_emails_external_id", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_analysis_id", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_message_id", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_matched_lead_id", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_received_at", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_processed", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_sender_email", table_name="incoming_emails")
    op.drop_index("ix_incoming_emails_id", table_name="incoming_emails")
    op.drop_table("incoming_emails")
