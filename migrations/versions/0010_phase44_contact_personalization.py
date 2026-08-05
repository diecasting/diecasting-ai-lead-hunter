"""Phase 4 Stage 4: Contact-Aware Outreach Personalization

Adds ``recipient_name`` and ``recipient_email`` to ``outreach_messages`` so
each generated draft records who it is addressed to (captured from the lead's
``contact_name`` / ``contact_email`` at generation time). The personalized
greeting in the email body is derived from the same contact info.

Revision ID: 0010_phase44_contact_personalization
Revises: 0009_phase435_lead_import
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_phase44_contact_personalization"
down_revision = "0009_phase435_lead_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_messages",
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outreach_messages",
        sa.Column("recipient_email", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_messages", "recipient_email")
    op.drop_column("outreach_messages", "recipient_name")
