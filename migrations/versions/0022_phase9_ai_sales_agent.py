"""Phase 9: AI Sales Agent

Revision ID: 0022_phase9_ai_sales_agent
Revises: 0021_phase85_contact_intelligence
Create Date: 2026-08-07

Creates the ``email_drafts`` table — AI-generated, contact-personalised sales
email drafts produced by the AI Sales Agent. This is independent of the Outreach
Engine's ``outreach_messages`` send pipeline. Links back to ``company_leads``
(CASCADE), ``contacts`` (SET NULL) and ``email_addresses`` (SET NULL).
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_phase9_ai_sales_agent"
down_revision = "0021_phase85_contact_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "email_address_id",
            sa.Integer(),
            sa.ForeignKey("email_addresses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("to_name", sa.String(length=255), nullable=True),
        sa.Column("to_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("opening", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("call_to_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("role_category", sa.String(length=40), nullable=True),
        sa.Column("prompt_role", sa.String(length=40), nullable=True),
        sa.Column("personalization_score", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("research_summary", sa.Text(), nullable=True),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_drafts_company_id", "email_drafts", ["company_id"])
    op.create_index("ix_email_drafts_contact_id", "email_drafts", ["contact_id"])
    op.create_index("ix_email_drafts_status", "email_drafts", ["status"])
    op.create_index("ix_email_drafts_role_category", "email_drafts", ["role_category"])
    op.create_index(
        "ix_email_drafts_personalization_score", "email_drafts", ["personalization_score"]
    )
    op.create_index("ix_email_drafts_quality_score", "email_drafts", ["quality_score"])


def downgrade() -> None:
    op.drop_index("ix_email_drafts_quality_score", table_name="email_drafts")
    op.drop_index("ix_email_drafts_personalization_score", table_name="email_drafts")
    op.drop_index("ix_email_drafts_role_category", table_name="email_drafts")
    op.drop_index("ix_email_drafts_status", table_name="email_drafts")
    op.drop_index("ix_email_drafts_contact_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_company_id", table_name="email_drafts")
    op.drop_table("email_drafts")
