"""Phase 4 Stage 0: Email Verification + Outreach Quality Gate

Revision ID: 0007_phase40_email_quality_gate
Revises: 0006_phase32_lead_scoring
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_phase40_email_quality_gate"
down_revision = "0006_phase32_lead_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend email_verifications with richer verification payload.
    op.add_column(
        "email_verifications", sa.Column("score", sa.Integer(), nullable=True)
    )
    op.add_column(
        "email_verifications", sa.Column("verifier", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "email_verifications", sa.Column("checks", sa.Text(), nullable=True)
    )
    op.create_index(
        "ix_email_verifications_score", "email_verifications", ["score"]
    )
    op.create_index(
        "ix_email_verifications_verifier", "email_verifications", ["verifier"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_verifications_verifier", table_name="email_verifications")
    op.drop_index("ix_email_verifications_score", table_name="email_verifications")
    op.drop_column("email_verifications", "checks")
    op.drop_column("email_verifications", "verifier")
    op.drop_column("email_verifications", "score")
