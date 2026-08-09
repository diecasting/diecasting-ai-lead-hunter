"""Phase 13.2: Contact Discovery Engine

Revision ID: 0029_phase13_contact_discovery
Revises: 0028_phase13_contact_discovery
Create Date: 2026-08-09

Phase 13.2 adds three additive, nullable and indexed columns to the existing
``contacts`` table so the Contact Discovery Engine can record *where* a contact
was found and *how confident* it is:

  * ``source_url``     -- the precise page / PDF URL the contact was mined from
  * ``discovery_score`` -- deterministic 0-100 discovery-quality score
  * ``confidence``     -- label derived from the score (high / medium / low)

No new tables are introduced (the audit-trail is provided by the existing
``contact_discovery_logs`` table added in Phase 13.1, and provenance by the
``discovery_method`` columns added there too). Purely additive, single head.
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_phase13_contact_discovery"
down_revision = "0028_phase13_contact_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("source_url", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_contacts_source_url", "contacts", ["source_url"]
    )

    op.add_column(
        "contacts",
        sa.Column("discovery_score", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_contacts_discovery_score", "contacts", ["discovery_score"]
    )

    op.add_column(
        "contacts",
        sa.Column("confidence", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_contacts_confidence", "contacts", ["confidence"]
    )


def downgrade() -> None:
    op.drop_index("ix_contacts_confidence", table_name="contacts")
    op.drop_column("contacts", "confidence")

    op.drop_index("ix_contacts_discovery_score", table_name="contacts")
    op.drop_column("contacts", "discovery_score")

    op.drop_index("ix_contacts_source_url", table_name="contacts")
    op.drop_column("contacts", "source_url")
