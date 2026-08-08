"""Phase 10: Reply Intelligence Sales Automation

Revision ID: 0024_phase10_reply_intelligence
Revises: 0023_phase95_campaign_engine
Create Date: 2026-08-07

Creates two tables that extend the existing Phase 6 Reply Intelligence engine:

  * ``sales_tasks``          — follow-up actions created from classified
    replies (FKs to reply_analyses / contacts / company_leads all SET NULL;
    indexed by status / priority / category / due_at for queueing).
  * ``reply_rfq_extractions``— structured RFQ requirements extracted from an
    ``rfq_request`` reply, attached to reply_analyses with CASCADE delete.

This migration is strictly additive: it never touches the existing
reply_analyses, incoming_emails, campaigns or CRM tables, so the Phase 6 inbox
/ classifier / analyzer behaviour is fully preserved.
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_phase10_reply_intelligence"
down_revision = "0023_phase95_campaign_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "reply_id",
            sa.Integer(),
            sa.ForeignKey("reply_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False,
                  server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="open"),
        sa.Column("category", sa.String(length=60), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_tasks_reply_id", "sales_tasks", ["reply_id"])
    op.create_index("ix_sales_tasks_contact_id", "sales_tasks", ["contact_id"])
    op.create_index("ix_sales_tasks_company_id", "sales_tasks", ["company_id"])
    op.create_index("ix_sales_tasks_status", "sales_tasks", ["status"])
    op.create_index("ix_sales_tasks_priority", "sales_tasks", ["priority"])
    op.create_index("ix_sales_tasks_category", "sales_tasks", ["category"])
    op.create_index("ix_sales_tasks_due_at", "sales_tasks", ["due_at"])

    op.create_table(
        "reply_rfq_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("reply_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Text(), nullable=True),
        sa.Column("material", sa.Text(), nullable=True),
        sa.Column("process", sa.Text(), nullable=True),
        sa.Column("deadline", sa.Text(), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reply_rfq_extractions_analysis_id",
        "reply_rfq_extractions",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reply_rfq_extractions_analysis_id",
        table_name="reply_rfq_extractions",
    )
    op.drop_table("reply_rfq_extractions")

    op.drop_index("ix_sales_tasks_due_at", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_category", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_priority", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_status", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_company_id", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_contact_id", table_name="sales_tasks")
    op.drop_index("ix_sales_tasks_reply_id", table_name="sales_tasks")
    op.drop_table("sales_tasks")
