"""Phase 15.3.5: Conversion Task Deduplication field

Revision ID: 0034_phase15_task_dedup
Revises: 0033_phase15_next_action
Create Date: 2026-08-10

Adds a stable ``conversion_action`` tag to ``sales_tasks`` so tasks created by
the Phase 10 reply flow can be de-duplicated against tasks accepted via the
Phase 15.3.3 conversion API. De-duplication key: (company_id, conversion_action,
status=open).

Purely additive, single head. No existing column or table is modified; the
downgrade drops only this one column.
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_phase15_task_dedup"
down_revision = "0033_phase15_next_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sales_tasks",
        sa.Column("conversion_action", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_sales_tasks_conversion_action",
        "sales_tasks",
        ["conversion_action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sales_tasks_conversion_action", table_name="sales_tasks")
    op.drop_column("sales_tasks", "conversion_action")
