"""Phase 4 Stage 3: Email Draft Quality Auto-Gate

Adds the ``quality_gate_status`` column to ``outreach_messages`` so each draft
carries a discrete gate decision (ready | review | blocked) derived from its
``quality_score``. The value is set at generation time and can be overridden by
a reviewer via PATCH /outreach/drafts/{id}/gate.

Revision ID: 0008_phase43_draft_quality_gate
Revises: 0007_phase40_email_quality_gate
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_phase43_draft_quality_gate"
down_revision = "0007_phase40_email_quality_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_messages",
        sa.Column("quality_gate_status", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_outreach_messages_quality_gate_status",
        "outreach_messages",
        ["quality_gate_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outreach_messages_quality_gate_status", table_name="outreach_messages"
    )
    op.drop_column("outreach_messages", "quality_gate_status")
