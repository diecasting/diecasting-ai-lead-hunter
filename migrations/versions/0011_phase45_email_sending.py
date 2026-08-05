"""Phase 4 Stage 5: Email Sending Pipeline

Adds the sending pipeline state to ``outreach_messages``:
``send_status`` (draft | queued | sent | failed, default draft) and
``sent_at`` (the moment the message was actually delivered). The new
``POST /outreach/drafts/{id}/send`` endpoint drives this state machine.

Revision ID: 0011_phase45_email_sending
Revises: 0010_phase44_contact_personalization
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_phase45_email_sending"
down_revision = "0010_phase44_contact_personalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_messages",
        sa.Column(
            "send_status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
    )
    op.create_index(
        "ix_outreach_messages_send_status", "outreach_messages", ["send_status"]
    )
    op.add_column(
        "outreach_messages",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_messages", "sent_at")
    op.drop_index("ix_outreach_messages_send_status", table_name="outreach_messages")
    op.drop_column("outreach_messages", "send_status")
