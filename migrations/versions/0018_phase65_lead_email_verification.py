"""Phase 6.5: Lead e-mail verification columns

Revision ID: 0018_phase65_lead_email_verification
Revises: 0017_phase63_reply_inbox
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_phase65_lead_email_verification"
down_revision = "0017_phase63_reply_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_leads",
        sa.Column(
            "email_status",
            sa.String(length=20),
            nullable=True,
            server_default="unknown",
        ),
    )
    op.add_column(
        "company_leads",
        sa.Column("email_confidence_score", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_company_leads_email_status", "company_leads", ["email_status"]
    )
    op.create_index(
        "ix_company_leads_email_confidence_score",
        "company_leads",
        ["email_confidence_score"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_leads_email_confidence_score", table_name="company_leads"
    )
    op.drop_index("ix_company_leads_email_status", table_name="company_leads")
    op.drop_column("company_leads", "email_confidence_score")
    op.drop_column("company_leads", "email_status")
