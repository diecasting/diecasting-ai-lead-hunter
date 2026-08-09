"""Phase 12.2: Quotation Intelligence Engine

Revision ID: 0027_phase12_quotation_engine
Revises: 0026_phase12_manufacturing_intelligence
Create Date: 2026-08-09

Adds the quotation engine layer on top of the Phase 12.1 manufacturing
intelligence foundation. Purely additive -- three new tables, no ALTER of
existing columns:

  * ``quotes`` -- a quotation header (deal link, status, currency, the
    deterministic cost rollup totals, margin and suggested price).
  * ``quote_line_items`` -- per-line cost breakdown, each tracing back to a
    ``cost_rates`` row via ``cost_rate_id`` (CASCADE with its quote).
  * ``quote_versions`` -- append-only version snapshots for audit (mirrors
    ``opportunity_stage_history``).

No QuoteApproval table yet (deferred).
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_phase12_quotation_engine"
down_revision = "0026_phase12_manufacturing_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "opportunity_id",
            sa.Integer(),
            sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requirement_id",
            sa.Integer(),
            sa.ForeignKey("product_requirements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("total_material_cost", sa.Float(), nullable=True),
        sa.Column("total_machine_cost", sa.Float(), nullable=True),
        sa.Column("total_cnc_cost", sa.Float(), nullable=True),
        sa.Column("total_tooling_cost", sa.Float(), nullable=True),
        sa.Column("total_finishing_cost", sa.Float(), nullable=True),
        sa.Column("total_overhead", sa.Float(), nullable=True),
        sa.Column("subtotal", sa.Float(), nullable=True),
        sa.Column("margin_pct", sa.Float(), nullable=True),
        sa.Column("margin_amount", sa.Float(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quotes_opportunity_id", "quotes", ["opportunity_id"])
    op.create_index("ix_quotes_requirement_id", "quotes", ["requirement_id"])
    op.create_index("ix_quotes_rfq_id", "quotes", ["rfq_id"])
    op.create_index("ix_quotes_company_id", "quotes", ["company_id"])
    op.create_index("ix_quotes_status", "quotes", ["status"])

    op.create_table(
        "quote_line_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "quote_id",
            sa.Integer(),
            sa.ForeignKey("quotes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cost_rate_id",
            sa.Integer(),
            sa.ForeignKey("cost_rates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("line_type", sa.String(length=20), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("unit_rate", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_line_items_quote_id", "quote_line_items", ["quote_id"])
    op.create_index("ix_quote_line_items_line_type", "quote_line_items", ["line_type"])
    op.create_index(
        "ix_quote_line_items_cost_rate_id", "quote_line_items", ["cost_rate_id"]
    )

    op.create_table(
        "quote_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "quote_id",
            sa.Integer(),
            sa.ForeignKey("quotes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("snapshot", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_versions_quote_id", "quote_versions", ["quote_id"])
    op.create_index("ix_quote_versions_version", "quote_versions", ["version"])


def downgrade() -> None:
    op.drop_index("ix_quote_versions_version", table_name="quote_versions")
    op.drop_index("ix_quote_versions_quote_id", table_name="quote_versions")
    op.drop_table("quote_versions")

    op.drop_index(
        "ix_quote_line_items_cost_rate_id", table_name="quote_line_items"
    )
    op.drop_index("ix_quote_line_items_line_type", table_name="quote_line_items")
    op.drop_index("ix_quote_line_items_quote_id", table_name="quote_line_items")
    op.drop_table("quote_line_items")

    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_company_id", table_name="quotes")
    op.drop_index("ix_quotes_rfq_id", table_name="quotes")
    op.drop_index("ix_quotes_requirement_id", table_name="quotes")
    op.drop_index("ix_quotes_opportunity_id", table_name="quotes")
    op.drop_table("quotes")
