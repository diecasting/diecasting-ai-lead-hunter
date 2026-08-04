"""Phase 2.3: add industrial lead intelligence columns + company_documents table

Adds to ``company_leads``:
  cnc_need_score, tooling_need_score, business_type, materials,
  manufacturing_process, buying_signal

Creates ``company_documents`` for storing extracted PDF / brochure text.

Revision ID: 0002_phase23
Revises: 0001_initial
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_phase23"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- New columns on company_leads ----------------------------------------
    op.add_column("company_leads", sa.Column("cnc_need_score", sa.Integer(), nullable=True))
    op.add_column("company_leads", sa.Column("tooling_need_score", sa.Integer(), nullable=True))
    op.add_column("company_leads", sa.Column("business_type", sa.String(length=80), nullable=True))
    op.add_column("company_leads", sa.Column("materials", sa.Text(), nullable=True))
    op.add_column("company_leads", sa.Column("manufacturing_process", sa.Text(), nullable=True))
    op.add_column("company_leads", sa.Column("buying_signal", sa.Text(), nullable=True))

    op.create_index("ix_company_leads_cnc_need_score", "company_leads", ["cnc_need_score"])
    op.create_index("ix_company_leads_tooling_need_score", "company_leads", ["tooling_need_score"])

    # --- company_documents table ---------------------------------------------
    op.create_table(
        "company_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_documents_id", "company_documents", ["id"])
    op.create_index("ix_company_documents_lead_id", "company_documents", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_company_documents_lead_id", table_name="company_documents")
    op.drop_index("ix_company_documents_id", table_name="company_documents")
    op.drop_table("company_documents")

    op.drop_index("ix_company_leads_tooling_need_score", table_name="company_leads")
    op.drop_index("ix_company_leads_cnc_need_score", table_name="company_leads")
    op.drop_column("company_leads", "buying_signal")
    op.drop_column("company_leads", "manufacturing_process")
    op.drop_column("company_leads", "materials")
    op.drop_column("company_leads", "business_type")
    op.drop_column("company_leads", "tooling_need_score")
    op.drop_column("company_leads", "cnc_need_score")
