"""Phase 6 Stage 1: AI Follow-up Automation Engine

Adds ``followup_sequences`` (named, ordered follow-up cadences with JSON
steps) and ``outreach_followups`` (per-lead scheduled follow-ups tied to the
original sent message, with a pending → generated → sent / cancelled
lifecycle).

Revision ID: 0015_phase61_followup_automation
Revises: 0014_phase53_discovery_scheduler
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_phase61_followup_automation"
down_revision = "0014_phase53_discovery_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "followup_sequences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_followup_sequences_name", "followup_sequences", ["name"])
    op.create_index("ix_followup_sequences_enabled", "followup_sequences", ["enabled"])

    op.create_table(
        "outreach_followups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("original_message_id", sa.Integer(), nullable=True),
        sa.Column("sequence_id", sa.Integer(), nullable=True),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["original_message_id"], ["outreach_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["followup_sequences.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["outreach_messages.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_outreach_followups_lead_id", "outreach_followups", ["lead_id"])
    op.create_index("ix_outreach_followups_status", "outreach_followups", ["status"])
    op.create_index("ix_outreach_followups_scheduled_at", "outreach_followups", ["scheduled_at"])
    op.create_index("ix_outreach_followups_sequence_id", "outreach_followups", ["sequence_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_followups_sequence_id", table_name="outreach_followups")
    op.drop_index("ix_outreach_followups_scheduled_at", table_name="outreach_followups")
    op.drop_index("ix_outreach_followups_status", table_name="outreach_followups")
    op.drop_index("ix_outreach_followups_lead_id", table_name="outreach_followups")
    op.drop_table("outreach_followups")
    op.drop_index("ix_followup_sequences_enabled", table_name="followup_sequences")
    op.drop_index("ix_followup_sequences_name", table_name="followup_sequences")
    op.drop_table("followup_sequences")
