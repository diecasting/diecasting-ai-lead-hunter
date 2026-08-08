"""Phase 12.1: Manufacturing Intelligence Foundation

Revision ID: 0026_phase12_manufacturing_intelligence
Revises: 0025_phase11_sales_pipeline
Create Date: 2026-08-09

Adds the manufacturing intelligence foundation layer that sits underneath the
future quotation engine (Phase 12). It is strictly additive and introduces
three new tables, none of which alter existing columns:

  * ``manufacturing_capabilities`` — OUR factory's "can we make it?" data
    (process / machine_type / tonnage / material compatibility / max part
    weight / tolerance capability / active flag). Distinct from cost.
  * ``cost_rates`` — the editable price/cost book ("what does it cost?"):
    material cost, machine hourly cost, labor cost, tooling cost and overhead,
    all carried in one flexible (category, code, rate) table.
  * ``product_requirements`` — the structured, quotation-ready interpretation of
    a customer RFQ, linked (SET NULL) to the originating reply_rfq_extraction,
    the opportunity it belongs to, and the company_lead.

No quotation engine, pricing calculation, AI quotation or Quote models are
introduced here — those are later Phase 12 steps.
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_phase12_manufacturing_intelligence"
down_revision = "0025_phase11_sales_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manufacturing_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process", sa.String(length=80), nullable=True),
        sa.Column("machine_type", sa.String(length=80), nullable=True),
        sa.Column("tonnage", sa.Integer(), nullable=True),
        sa.Column("material_compatibility", sa.Text(), nullable=True),
        sa.Column("max_part_weight", sa.Float(), nullable=True),
        sa.Column("tolerance_capability", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_manufacturing_capabilities_process",
        "manufacturing_capabilities",
        ["process"],
    )
    op.create_index(
        "ix_manufacturing_capabilities_active",
        "manufacturing_capabilities",
        ["active"],
    )

    op.create_table(
        "cost_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("rate", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "category",
            "code",
            "effective_from",
            name="uq_cost_rates_category_code_effective",
        ),
    )
    op.create_index("ix_cost_rates_category", "cost_rates", ["category"])
    op.create_index("ix_cost_rates_code", "cost_rates", ["code"])

    op.create_table(
        "product_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "opportunity_id",
            sa.Integer(),
            sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("material", sa.String(length=80), nullable=True),
        sa.Column("process", sa.String(length=80), nullable=True),
        sa.Column("annual_volume", sa.Integer(), nullable=True),
        sa.Column("tolerance", sa.String(length=40), nullable=True),
        sa.Column("finishing", sa.String(length=80), nullable=True),
        sa.Column("complexity", sa.String(length=20), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_requirements_rfq_id", "product_requirements", ["rfq_id"]
    )
    op.create_index(
        "ix_product_requirements_opportunity_id",
        "product_requirements",
        ["opportunity_id"],
    )
    op.create_index(
        "ix_product_requirements_company_id",
        "product_requirements",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_requirements_company_id", table_name="product_requirements"
    )
    op.drop_index(
        "ix_product_requirements_opportunity_id",
        table_name="product_requirements",
    )
    op.drop_index(
        "ix_product_requirements_rfq_id", table_name="product_requirements"
    )
    op.drop_table("product_requirements")

    op.drop_index("ix_cost_rates_code", table_name="cost_rates")
    op.drop_index("ix_cost_rates_category", table_name="cost_rates")
    op.drop_table("cost_rates")

    op.drop_index(
        "ix_manufacturing_capabilities_active",
        table_name="manufacturing_capabilities",
    )
    op.drop_index(
        "ix_manufacturing_capabilities_process",
        table_name="manufacturing_capabilities",
    )
    op.drop_table("manufacturing_capabilities")
