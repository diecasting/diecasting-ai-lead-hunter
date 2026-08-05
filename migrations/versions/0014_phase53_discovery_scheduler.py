"""Phase 5 Stage 3: Discovery Scheduler and Lead Qualification

Adds ``discovery_schedules`` (recurring keyword-driven discovery runs with
auto-qualification thresholds) and links ``discovery_jobs`` to their owning
schedule (``schedule_id``) so execution history is queryable per schedule.

Revision ID: 0014_phase53_discovery_scheduler
Revises: 0013_phase52_discovery_queue
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_phase53_discovery_scheduler"
down_revision = "0013_phase52_discovery_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column(
            "frequency", sa.String(length=20), nullable=False, server_default="daily"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "lead_score_threshold", sa.Integer(), nullable=False, server_default="50"
        ),
        sa.Column(
            "confidence_threshold", sa.Integer(), nullable=False, server_default="40"
        ),
        sa.Column("last_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_discovery_schedules_keyword", "discovery_schedules", ["keyword"]
    )
    op.create_index("ix_discovery_schedules_enabled", "discovery_schedules", ["enabled"])

    op.add_column(
        "discovery_jobs",
        sa.Column("schedule_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_discovery_jobs_schedule_id", "discovery_jobs", ["schedule_id"])
    op.create_foreign_key(
        "fk_discovery_jobs_schedule_id",
        "discovery_jobs",
        "discovery_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_discovery_jobs_schedule_id", "discovery_jobs", type_="foreignkey")
    op.drop_index("ix_discovery_jobs_schedule_id", table_name="discovery_jobs")
    op.drop_column("discovery_jobs", "schedule_id")
    op.drop_index("ix_discovery_schedules_enabled", table_name="discovery_schedules")
    op.drop_index("ix_discovery_schedules_keyword", table_name="discovery_schedules")
    op.drop_table("discovery_schedules")
