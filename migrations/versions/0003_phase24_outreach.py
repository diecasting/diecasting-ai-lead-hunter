"""Phase 2.4: add outreach_messages table for AI-generated sales emails

Revision ID: 0003_phase24_outreach
Revises: 0002_phase23
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_phase24_outreach"
down_revision = "0002_phase23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("contact_role", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["company_leads.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_messages_id", "outreach_messages", ["id"])
    op.create_index("ix_outreach_messages_lead_id", "outreach_messages", ["lead_id"])
    op.create_index("ix_outreach_messages_status", "outreach_messages", ["status"])


def downgrade() -> None:
    op.drop_index("ix_outreach_messages_status", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_lead_id", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_id", table_name="outreach_messages")
    op.drop_table("outreach_messages")
