"""Phase 5 Stage 1: AI Lead Discovery Engine

Adds the ``company_discoveries`` table storing website-analysis results for
prospective industrial manufacturers (extracted profile, provenance, confidence,
lead score, recommended contact role) until the operator adds them to the CRM.

Revision ID: 0012_phase51_lead_discovery
Revises: 0011_phase45_email_sending
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_phase51_lead_discovery"
down_revision = "0011_phase45_email_sending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("detected_materials", sa.Text(), nullable=True),
        sa.Column("detected_processes", sa.Text(), nullable=True),
        sa.Column("buying_signals", sa.Text(), nullable=True),
        sa.Column(
            "discovery_source",
            sa.String(length=120),
            nullable=False,
            server_default="url_analysis",
        ),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("lead_score", sa.Integer(), nullable=True),
        sa.Column("recommended_contact_role", sa.String(length=120), nullable=True),
        sa.Column("profile", sa.Text(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_company_discoveries_company_name", "company_discoveries", ["company_name"])
    op.create_index("ix_company_discoveries_website", "company_discoveries", ["website"])
    op.create_index("ix_company_discoveries_discovery_source", "company_discoveries", ["discovery_source"])
    op.create_index("ix_company_discoveries_lead_id", "company_discoveries", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_company_discoveries_lead_id", table_name="company_discoveries")
    op.drop_index("ix_company_discoveries_discovery_source", table_name="company_discoveries")
    op.drop_index("ix_company_discoveries_website", table_name="company_discoveries")
    op.drop_index("ix_company_discoveries_company_name", table_name="company_discoveries")
    op.drop_table("company_discoveries")
