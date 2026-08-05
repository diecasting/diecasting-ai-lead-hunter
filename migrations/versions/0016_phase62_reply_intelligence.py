"""Phase 6 Stage 2: AI Reply Intelligence Engine

Adds ``reply_analyses`` — one row per classified inbound customer reply,
holding the detected intent, its confidence, and the recommended CRM action.

Revision ID: 0016_phase62_reply_intelligence
Revises: 0015_phase61_followup_automation
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_phase62_reply_intelligence"
down_revision = "0015_phase61_followup_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reply_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("recommended_action", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["outreach_messages.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_reply_analyses_lead_id", "reply_analyses", ["lead_id"])
    op.create_index("ix_reply_analyses_intent", "reply_analyses", ["intent"])
    op.create_index("ix_reply_analyses_message_id", "reply_analyses", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_reply_analyses_message_id", table_name="reply_analyses")
    op.drop_index("ix_reply_analyses_intent", table_name="reply_analyses")
    op.drop_index("ix_reply_analyses_lead_id", table_name="reply_analyses")
    op.drop_table("reply_analyses")
