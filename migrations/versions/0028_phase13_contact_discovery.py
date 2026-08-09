"""Phase 13.1: Contact Discovery Foundation

Revision ID: 0028_phase13_contact_discovery
Revises: 0027_phase12_quotation_engine
Create Date: 2026-08-09

Adds the foundation layer for the Contact Discovery Intelligence engine:

  * ``contact_discovery_logs`` -- a per-company / per-domain / per-method scan
    history so discovery engines avoid re-scanning the same target repeatedly
    and operators get an audit trail. Ownership FK to ``company_leads`` is
    CASCADE (deleting a lead removes its discovery history).

  * ``email_addresses.discovery_method`` -- nullable, additive provenance
    column (website / pdf / pattern / external) recording which discovery
    engine found the address. Defaults to "website".

  * ``contacts.discovery_method`` -- same nullable, additive provenance column
    for discovered contacts. Defaults to "website".

Purely additive: one new table + two new columns. No ALTER of existing data,
no destructive changes. A single alembic head is preserved.
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_phase13_contact_discovery"
down_revision = "0027_phase12_quotation_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_discovery_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company_leads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column(
            "method",
            sa.String(length=20),
            nullable=False,
            server_default="website",
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contacts_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="done",
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contact_discovery_logs_company_id", "contact_discovery_logs", ["company_id"]
    )
    op.create_index(
        "ix_contact_discovery_logs_domain", "contact_discovery_logs", ["domain"]
    )
    op.create_index(
        "ix_contact_discovery_logs_company_method",
        "contact_discovery_logs",
        ["company_id", "method"],
    )

    # Additive provenance columns (nullable, default "website").
    op.add_column(
        "email_addresses",
        sa.Column(
            "discovery_method",
            sa.String(length=20),
            nullable=True,
            server_default="website",
        ),
    )
    op.create_index(
        "ix_email_addresses_discovery_method", "email_addresses", ["discovery_method"]
    )

    op.add_column(
        "contacts",
        sa.Column(
            "discovery_method",
            sa.String(length=20),
            nullable=True,
            server_default="website",
        ),
    )
    op.create_index(
        "ix_contacts_discovery_method", "contacts", ["discovery_method"]
    )


def downgrade() -> None:
    op.drop_index("ix_contacts_discovery_method", table_name="contacts")
    op.drop_column("contacts", "discovery_method")

    op.drop_index("ix_email_addresses_discovery_method", table_name="email_addresses")
    op.drop_column("email_addresses", "discovery_method")

    op.drop_index(
        "ix_contact_discovery_logs_company_method", table_name="contact_discovery_logs"
    )
    op.drop_index("ix_contact_discovery_logs_domain", table_name="contact_discovery_logs")
    op.drop_index(
        "ix_contact_discovery_logs_company_id", table_name="contact_discovery_logs"
    )
    op.drop_table("contact_discovery_logs")
