"""Phase 11: Sales Pipeline Opportunity Engine

Revision ID: 0025_phase11_sales_pipeline
Revises: 0024_phase10_reply_intelligence
Create Date: 2026-08-08

Adds the deal-level sales pipeline that sits on top of the existing lead
funnel (``CompanyLead.lead_status``):

  * ``opportunities``             — revenue opportunities tracked through a
    stage / amount / probability / expected-close-date, traced back to the
    reply / RFQ that created them (FKs to company_leads / contacts /
    reply_analyses / reply_rfq_extractions all SET NULL).
  * ``opportunity_stage_history`` — append-only audit log of stage transitions
    (mirrors the ``OutreachEvent`` timeline), CASCADE-deleted with the opp.

It also adds a nullable ``opportunity_id`` FK to ``sales_tasks`` (SET NULL) so
a follow-up task can be linked to the deal it supports.

This migration is strictly additive: it never alters the existing
company_leads, contacts, reply_analyses, reply_rfq_extractions or
sales_tasks columns, so the Phase 6 / 10 / 10.5 behaviour is fully preserved.
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_phase11_sales_pipeline"
down_revision = "0024_phase10_reply_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reply_id",
            sa.Integer(),
            sa.ForeignKey("reply_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage", sa.String(length=20), nullable=False,
                  server_default="prospecting"),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False,
                  server_default="USD"),
        sa.Column("probability", sa.Integer(), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("actual_close_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False,
                  server_default="medium"),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opportunities_company_id", "opportunities", ["company_id"])
    op.create_index("ix_opportunities_contact_id", "opportunities", ["contact_id"])
    op.create_index("ix_opportunities_reply_id", "opportunities", ["reply_id"])
    op.create_index("ix_opportunities_rfq_id", "opportunities", ["rfq_id"])
    op.create_index("ix_opportunities_stage", "opportunities", ["stage"])
    op.create_index("ix_opportunities_priority", "opportunities", ["priority"])
    op.create_index("ix_opportunities_probability", "opportunities", ["probability"])

    op.create_table(
        "opportunity_stage_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "opportunity_id",
            sa.Integer(),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_stage", sa.String(length=20), nullable=True),
        sa.Column("to_stage", sa.String(length=20), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunity_stage_history_opportunity_id",
        "opportunity_stage_history",
        ["opportunity_id"],
    )

    # SQLite cannot ALTER TABLE ... ADD COLUMN with a FK inline; use batch mode
    # so the migration is portable across SQLite (dev) and PostgreSQL (prod).
    with op.batch_alter_table("sales_tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "opportunity_id",
                sa.Integer(),
                sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_sales_tasks_opportunity_id", ["opportunity_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("sales_tasks") as batch_op:
        batch_op.drop_index("ix_sales_tasks_opportunity_id")
        batch_op.drop_column("opportunity_id")

    op.drop_index(
        "ix_opportunity_stage_history_opportunity_id",
        table_name="opportunity_stage_history",
    )
    op.drop_table("opportunity_stage_history")

    op.drop_index("ix_opportunities_probability", table_name="opportunities")
    op.drop_index("ix_opportunities_priority", table_name="opportunities")
    op.drop_index("ix_opportunities_stage", table_name="opportunities")
    op.drop_index("ix_opportunities_rfq_id", table_name="opportunities")
    op.drop_index("ix_opportunities_reply_id", table_name="opportunities")
    op.drop_index("ix_opportunities_contact_id", table_name="opportunities")
    op.drop_index("ix_opportunities_company_id", table_name="opportunities")
    op.drop_table("opportunities")
