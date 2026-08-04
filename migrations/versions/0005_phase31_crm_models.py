"""Phase 3 Stage 1: CRM data model upgrade

Revision ID: 0005_phase31_crm_models
Revises: 0004_phase25_crm
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_phase31_crm_models"
down_revision = "0004_phase25_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- contacts ------------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=160), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_id", "contacts", ["id"])
    op.create_index("ix_contacts_lead_id", "contacts", ["lead_id"])
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_index("ix_contacts_is_primary", "contacts", ["is_primary"])
    op.create_index("ix_contacts_do_not_contact", "contacts", ["do_not_contact"])

    # --- lead_sources --------------------------------------------------------
    op.create_table(
        "lead_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_lead_sources_id", "lead_sources", ["id"])
    op.create_index("ix_lead_sources_name", "lead_sources", ["name"])
    op.create_index("ix_lead_sources_is_active", "lead_sources", ["is_active"])

    # --- email_verifications -------------------------------------------------
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("is_deliverable", sa.String(length=10), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_verifications_id", "email_verifications", ["id"])
    op.create_index("ix_email_verifications_contact_id", "email_verifications", ["contact_id"])
    op.create_index("ix_email_verifications_lead_id", "email_verifications", ["lead_id"])
    op.create_index("ix_email_verifications_email", "email_verifications", ["email"])
    op.create_index("ix_email_verifications_status", "email_verifications", ["status"])

    # --- email_tracking ------------------------------------------------------
    op.create_table(
        "email_tracking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["message_id"], ["outreach_messages.id"], ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("tracking_token", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_tracking_id", "email_tracking", ["id"])
    op.create_index("ix_email_tracking_message_id", "email_tracking", ["message_id"])
    op.create_index("ix_email_tracking_contact_id", "email_tracking", ["contact_id"])
    op.create_index("ix_email_tracking_event_type", "email_tracking", ["event_type"])
    op.create_index("ix_email_tracking_tracking_token", "email_tracking", ["tracking_token"])

    # --- reply_inbox ---------------------------------------------------------
    op.create_table(
        "reply_inbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["message_id"], ["outreach_messages.id"], ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_bounce", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reply_inbox_id", "reply_inbox", ["id"])
    op.create_index("ix_reply_inbox_message_id", "reply_inbox", ["message_id"])
    op.create_index("ix_reply_inbox_lead_id", "reply_inbox", ["lead_id"])
    op.create_index("ix_reply_inbox_contact_id", "reply_inbox", ["contact_id"])
    op.create_index("ix_reply_inbox_from_email", "reply_inbox", ["from_email"])
    op.create_index("ix_reply_inbox_is_bounce", "reply_inbox", ["is_bounce"])

    # --- unsubscribes --------------------------------------------------------
    op.create_table(
        "unsubscribes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"], ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("token", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_unsubscribes_id", "unsubscribes", ["id"])
    op.create_index("ix_unsubscribes_lead_id", "unsubscribes", ["lead_id"])
    op.create_index("ix_unsubscribes_contact_id", "unsubscribes", ["contact_id"])
    op.create_index("ix_unsubscribes_email", "unsubscribes", ["email"])
    op.create_index("ix_unsubscribes_token", "unsubscribes", ["token"])

    # --- company_leads extensions --------------------------------------------
    op.add_column(
        "company_leads",
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "company_leads",
        sa.Column("bounce_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "company_leads", sa.Column("acquisition_channel", sa.String(length=120), nullable=True)
    )
    op.create_index("ix_company_leads_do_not_contact", "company_leads", ["do_not_contact"])
    op.create_index("ix_company_leads_bounce_count", "company_leads", ["bounce_count"])
    op.create_index(
        "ix_company_leads_acquisition_channel", "company_leads", ["acquisition_channel"]
    )

    # --- outreach_messages extensions ----------------------------------------
    op.add_column(
        "outreach_messages", sa.Column("tracking_token", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "outreach_messages",
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outreach_messages",
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("outreach_messages", sa.Column("html_body", sa.Text(), nullable=True))
    op.create_index(
        "ix_outreach_messages_tracking_token", "outreach_messages", ["tracking_token"]
    )
    op.create_index("ix_outreach_messages_open_count", "outreach_messages", ["open_count"])
    op.create_index("ix_outreach_messages_click_count", "outreach_messages", ["click_count"])


def downgrade() -> None:
    op.drop_index("ix_outreach_messages_click_count", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_open_count", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_tracking_token", table_name="outreach_messages")
    op.drop_column("outreach_messages", "html_body")
    op.drop_column("outreach_messages", "click_count")
    op.drop_column("outreach_messages", "open_count")
    op.drop_column("outreach_messages", "tracking_token")

    op.drop_index("ix_company_leads_acquisition_channel", table_name="company_leads")
    op.drop_index("ix_company_leads_bounce_count", table_name="company_leads")
    op.drop_index("ix_company_leads_do_not_contact", table_name="company_leads")
    op.drop_column("company_leads", "acquisition_channel")
    op.drop_column("company_leads", "bounce_count")
    op.drop_column("company_leads", "do_not_contact")

    op.drop_index("ix_unsubscribes_token", table_name="unsubscribes")
    op.drop_index("ix_unsubscribes_email", table_name="unsubscribes")
    op.drop_index("ix_unsubscribes_contact_id", table_name="unsubscribes")
    op.drop_index("ix_unsubscribes_lead_id", table_name="unsubscribes")
    op.drop_index("ix_unsubscribes_id", table_name="unsubscribes")
    op.drop_table("unsubscribes")

    op.drop_index("ix_reply_inbox_is_bounce", table_name="reply_inbox")
    op.drop_index("ix_reply_inbox_from_email", table_name="reply_inbox")
    op.drop_index("ix_reply_inbox_contact_id", table_name="reply_inbox")
    op.drop_index("ix_reply_inbox_lead_id", table_name="reply_inbox")
    op.drop_index("ix_reply_inbox_message_id", table_name="reply_inbox")
    op.drop_index("ix_reply_inbox_id", table_name="reply_inbox")
    op.drop_table("reply_inbox")

    op.drop_index("ix_email_tracking_tracking_token", table_name="email_tracking")
    op.drop_index("ix_email_tracking_event_type", table_name="email_tracking")
    op.drop_index("ix_email_tracking_contact_id", table_name="email_tracking")
    op.drop_index("ix_email_tracking_message_id", table_name="email_tracking")
    op.drop_index("ix_email_tracking_id", table_name="email_tracking")
    op.drop_table("email_tracking")

    op.drop_index("ix_email_verifications_status", table_name="email_verifications")
    op.drop_index("ix_email_verifications_email", table_name="email_verifications")
    op.drop_index("ix_email_verifications_lead_id", table_name="email_verifications")
    op.drop_index("ix_email_verifications_contact_id", table_name="email_verifications")
    op.drop_index("ix_email_verifications_id", table_name="email_verifications")
    op.drop_table("email_verifications")

    op.drop_index("ix_lead_sources_is_active", table_name="lead_sources")
    op.drop_index("ix_lead_sources_name", table_name="lead_sources")
    op.drop_index("ix_lead_sources_id", table_name="lead_sources")
    op.drop_table("lead_sources")

    op.drop_index("ix_contacts_do_not_contact", table_name="contacts")
    op.drop_index("ix_contacts_is_primary", table_name="contacts")
    op.drop_index("ix_contacts_email", table_name="contacts")
    op.drop_index("ix_contacts_lead_id", table_name="contacts")
    op.drop_index("ix_contacts_id", table_name="contacts")
    op.drop_table("contacts")
