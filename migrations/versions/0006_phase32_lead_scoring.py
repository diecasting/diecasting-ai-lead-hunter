"""Phase 3 Stage 3: AI lead scoring & prioritization

Revision ID: 0006_phase32_lead_scoring
Revises: 0005_phase31_crm_models
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_phase32_lead_scoring"
down_revision = "0005_phase31_crm_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- company_leads: composite lead score + priority ----------------------
    op.add_column(
        "company_leads", sa.Column("lead_score", sa.Integer(), nullable=True)
    )
    op.add_column(
        "company_leads", sa.Column("lead_score_breakdown", sa.Text(), nullable=True)
    )
    op.add_column(
        "company_leads", sa.Column("priority", sa.String(length=10), nullable=True)
    )
    op.create_index("ix_company_leads_lead_score", "company_leads", ["lead_score"])
    op.create_index("ix_company_leads_priority", "company_leads", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_company_leads_priority", table_name="company_leads")
    op.drop_index("ix_company_leads_lead_score", table_name="company_leads")
    op.drop_column("company_leads", "priority")
    op.drop_column("company_leads", "lead_score_breakdown")
    op.drop_column("company_leads", "lead_score")
