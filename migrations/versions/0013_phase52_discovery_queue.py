"""Phase 5 Stage 2: Batch Lead Discovery Queue

Adds the discovery job/task tables that batch keyword-driven prospect
discovery: ``discovery_jobs`` (keyword + progress counters) and
``discovery_tasks`` (one row per candidate URL with its analysis outcome and
a link to the produced ``CompanyDiscovery``).

Revision ID: 0013_phase52_discovery_queue
Revises: 0012_phase51_lead_discovery
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_phase52_discovery_queue"
down_revision = "0012_phase51_lead_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "total_urls", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "processed_urls", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_discovery_jobs_keyword", "discovery_jobs", ["keyword"])
    op.create_index("ix_discovery_jobs_status", "discovery_jobs", ["status"])

    op.create_table(
        "discovery_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("discovery_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["discovery_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["discovery_id"], ["company_discoveries.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_discovery_tasks_job_id", "discovery_tasks", ["job_id"])
    op.create_index("ix_discovery_tasks_url", "discovery_tasks", ["url"])
    op.create_index("ix_discovery_tasks_status", "discovery_tasks", ["status"])
    op.create_index("ix_discovery_tasks_discovery_id", "discovery_tasks", ["discovery_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_tasks_discovery_id", table_name="discovery_tasks")
    op.drop_index("ix_discovery_tasks_status", table_name="discovery_tasks")
    op.drop_index("ix_discovery_tasks_url", table_name="discovery_tasks")
    op.drop_index("ix_discovery_tasks_job_id", table_name="discovery_tasks")
    op.drop_table("discovery_tasks")
    op.drop_index("ix_discovery_jobs_status", table_name="discovery_jobs")
    op.drop_index("ix_discovery_jobs_keyword", table_name="discovery_jobs")
    op.drop_table("discovery_jobs")
