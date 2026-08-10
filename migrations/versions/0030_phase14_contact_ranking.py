"""Phase 14.1: Contact Ranking Engine

Revision ID: 0030_phase14_contact_ranking
Revises: 0029_phase13_contact_discovery
Create Date: 2026-08-10

Phase 14.1 adds three additive, nullable columns to the existing ``contacts``
table so the Contact Ranking Engine can record a deterministic outreach-priority
score for each contact *before* outreach:

  * ``ranking_score``       -- 0-100 outreach-priority score
  * ``ranking_confidence``  -- high / medium / low (data completeness)
  * ``ranking_reason``      -- human-readable breakdown of the score

These are intentionally distinct from the Phase 13.2 ``discovery_score`` /
``confidence`` columns (which describe *discovery* quality) and never write to
them. Purely additive, single head.
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_phase14_contact_ranking"
down_revision = "0029_phase13_contact_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("ranking_score", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_contacts_ranking_score", "contacts", ["ranking_score"]
    )

    op.add_column(
        "contacts",
        sa.Column("ranking_confidence", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_contacts_ranking_confidence", "contacts", ["ranking_confidence"]
    )

    op.add_column(
        "contacts",
        sa.Column("ranking_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "ranking_reason")

    op.drop_index("ix_contacts_ranking_confidence", table_name="contacts")
    op.drop_column("contacts", "ranking_confidence")

    op.drop_index("ix_contacts_ranking_score", table_name="contacts")
    op.drop_column("contacts", "ranking_score")
