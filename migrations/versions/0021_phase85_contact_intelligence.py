"""Phase 8.5: Contact Intelligence Engine

Revision ID: 0021_phase85_contact_intelligence
Revises: 0020_phase8_email_discovery
Create Date: 2026-08-07

Extends the existing ``contacts`` table (created in Phase 3) with the Contact
Intelligence fields: provenance (``source``), title classification
(``title_category`` / ``seniority``), purchasing priority scoring
(``purchasing_score`` / ``priority``) and a link back to a discovered
``email_addresses`` row (``email_address_id``, SET NULL on delete).
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_phase85_contact_intelligence"
down_revision = "0020_phase8_email_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("source", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("title_category", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("seniority", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("purchasing_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("priority", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("email_address_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_contacts_title_category", "contacts", ["title_category"]
    )
    op.create_index(
        "ix_contacts_purchasing_score", "contacts", ["purchasing_score"]
    )
    op.create_index("ix_contacts_priority", "contacts", ["priority"])
    op.create_index(
        "ix_contacts_email_address_id", "contacts", ["email_address_id"]
    )

    # Link back to a discovered corporate e-mail (Phase 8 EmailAddress).
    op.create_foreign_key(
        "fk_contacts_email_address_id",
        "contacts",
        "email_addresses",
        ["email_address_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contacts_email_address_id", "contacts", type_="foreignkey"
    )
    op.drop_index("ix_contacts_email_address_id", table_name="contacts")
    op.drop_index("ix_contacts_priority", table_name="contacts")
    op.drop_index("ix_contacts_purchasing_score", table_name="contacts")
    op.drop_index("ix_contacts_title_category", table_name="contacts")

    op.drop_column("contacts", "discovered_at")
    op.drop_column("contacts", "email_address_id")
    op.drop_column("contacts", "priority")
    op.drop_column("contacts", "purchasing_score")
    op.drop_column("contacts", "seniority")
    op.drop_column("contacts", "title_category")
    op.drop_column("contacts", "source")
