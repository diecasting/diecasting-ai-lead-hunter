"""Phase 8: Email Discovery & Verification Engine

Revision ID: 0020_phase8_email_discovery
Revises: 0019_phase7_quora_seo_authority
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_phase8_email_discovery"
down_revision = "0019_phase7_quora_seo_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="website",
        ),
        sa.Column(
            "email_type",
            sa.String(length=20),
            nullable=False,
            server_default="generic",
        ),
        sa.Column(
            "verification_status",
            sa.String(length=20),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("verification_score", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company_leads.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_addresses_email", "email_addresses", ["email"])
    op.create_index(
        "ix_email_addresses_verification_score",
        "email_addresses",
        ["verification_score"],
    )
    op.create_index(
        "ix_email_addresses_company_id", "email_addresses", ["company_id"]
    )
    op.create_index(
        "ix_email_addresses_verification_status",
        "email_addresses",
        ["verification_status"],
    )
    op.create_index(
        "ix_email_addresses_company_email",
        "email_addresses",
        ["company_id", "email"],
        unique=True,
    )
    op.create_index(
        "ix_email_addresses_company_status",
        "email_addresses",
        ["company_id", "verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_addresses_company_status", table_name="email_addresses")
    op.drop_index("ix_email_addresses_company_email", table_name="email_addresses")
    op.drop_index(
        "ix_email_addresses_verification_status", table_name="email_addresses"
    )
    op.drop_index("ix_email_addresses_company_id", table_name="email_addresses")
    op.drop_index(
        "ix_email_addresses_verification_score", table_name="email_addresses"
    )
    op.drop_index("ix_email_addresses_email", table_name="email_addresses")
    op.drop_table("email_addresses")
