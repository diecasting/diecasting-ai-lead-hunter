"""Phase 9.5: AI Outreach Campaign Engine

Revision ID: 0023_phase95_campaign_engine
Revises: 0022_phase9_ai_sales_agent
Create Date: 2026-08-07

Creates the ``campaigns`` and ``campaign_contacts`` tables. The campaign engine
is additive: it targets companies / contacts selected from the existing
CompanyLead / Contact / EmailAddress infrastructure and stages generated
``email_drafts`` for sending. It never touches the Outreach Engine's
``outreach_messages`` send pipeline, so existing behaviour is preserved.

``campaign_contacts`` links back to ``company_leads`` / ``contacts`` /
``email_addresses`` / ``email_drafts`` with ``ondelete=SET NULL`` so analytics
history survives the deletion of an underlying row.
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_phase95_campaign_engine"
down_revision = "0022_phase9_ai_sales_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_industry", sa.String(length=160), nullable=True),
        sa.Column("target_country", sa.String(length=120), nullable=True),
        sa.Column("min_priority", sa.String(length=10), nullable=True),
        sa.Column("min_sales_priority", sa.String(length=10), nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("quality_gate_min", sa.Integer(), nullable=True),
        sa.Column("use_ai", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("tone", sa.String(length=40), nullable=False,
                  server_default="professional"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="draft"),
        sa.Column("total_targets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rfq_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_name", "campaigns", ["name"])
    op.create_index("ix_campaigns_target_industry", "campaigns", ["target_industry"])
    op.create_index("ix_campaigns_target_country", "campaigns", ["target_country"])
    op.create_index("ix_campaigns_min_priority", "campaigns", ["min_priority"])
    op.create_index(
        "ix_campaigns_min_sales_priority", "campaigns", ["min_sales_priority"]
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    op.create_table(
        "campaign_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
            "email_address_id",
            sa.Integer(),
            sa.ForeignKey("email_addresses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "draft_id",
            sa.Integer(),
            sa.ForeignKey("email_drafts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("to_name", sa.String(length=255), nullable=True),
        sa.Column("to_email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="selected"),
        sa.Column("priority_rank", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rfq_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaign_contacts_campaign_id", "campaign_contacts", ["campaign_id"]
    )
    op.create_index(
        "ix_campaign_contacts_company_id", "campaign_contacts", ["company_id"]
    )
    op.create_index(
        "ix_campaign_contacts_contact_id", "campaign_contacts", ["contact_id"]
    )
    op.create_index(
        "ix_campaign_contacts_draft_id", "campaign_contacts", ["draft_id"]
    )
    op.create_index(
        "ix_campaign_contacts_status", "campaign_contacts", ["status"]
    )
    op.create_index(
        "ix_campaign_contacts_priority_rank", "campaign_contacts", ["priority_rank"]
    )
    op.create_index(
        "ix_campaign_contacts_quality_score", "campaign_contacts", ["quality_score"]
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_contacts_quality_score", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_priority_rank", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_status", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_draft_id", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_contact_id", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_company_id", table_name="campaign_contacts")
    op.drop_index("ix_campaign_contacts_campaign_id", table_name="campaign_contacts")
    op.drop_table("campaign_contacts")

    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_campaigns_min_sales_priority", table_name="campaigns")
    op.drop_index("ix_campaigns_min_priority", table_name="campaigns")
    op.drop_index("ix_campaigns_target_country", table_name="campaigns")
    op.drop_index("ix_campaigns_target_industry", table_name="campaigns")
    op.drop_index("ix_campaigns_name", table_name="campaigns")
    op.drop_table("campaigns")
