"""Phase 4 Stage 3.5: Lead Import System

Adds ``lead_source`` (provenance tracking, default "import") and
``contact_name`` to ``company_leads`` so bulk-imported leads can be tagged and
identified in the dashboard, and the import can carry a named contact.

Backfill: rows that were bulk-imported earlier (``source = 'csv_import'``)
keep ``lead_source = 'import'`` (the column default); everything else
(dashboard-created, search-derived, crawled) becomes ``'manual'`` so the
provenance column is accurate for pre-existing data.

Revision ID: 0009_phase435_lead_import
Revises: 0008_phase43_draft_quality_gate
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_phase435_lead_import"
down_revision = "0008_phase43_draft_quality_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_leads",
        sa.Column(
            "lead_source",
            sa.String(length=50),
            nullable=False,
            server_default="import",
        ),
    )
    op.create_index(
        "ix_company_leads_lead_source", "company_leads", ["lead_source"]
    )
    op.add_column(
        "company_leads",
        sa.Column("contact_name", sa.String(length=255), nullable=True),
    )
    # Backfill provenance for pre-existing rows (idempotent on fresh DBs).
    op.execute(
        "UPDATE company_leads SET lead_source = 'manual' "
        "WHERE COALESCE(source, '') <> 'csv_import'"
    )


def downgrade() -> None:
    op.drop_index("ix_company_leads_lead_source", table_name="company_leads")
    op.drop_column("company_leads", "contact_name")
    op.drop_column("company_leads", "lead_source")
