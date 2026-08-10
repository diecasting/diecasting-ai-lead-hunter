"""Phase 15.4.2: Recommendation lifecycle closure

Revision ID: 0036_phase15_recommendation_closure
Revises: 0035_phase15_recommendation
Create Date: 2026-08-10

Adds the downstream closure columns to the ``recommendations`` table so an
accepted recommendation can be traced to the SalesTask (and later Opportunity)
it spawned, and records completion / expiry timestamps:

  * recommendations.sales_task_id   -> sales_tasks.id   (SET NULL, index)
  * recommendations.opportunity_id  -> opportunities.id (SET NULL, index)
  * recommendations.expired_at      -> DateTime, nullable

``completed_at`` already exists (added in 0035). All new FKs are ``SET NULL`` so
deleting an underlying task / opportunity never orphans a recommendation.

Purely additive, single head. Downgrade drops the two columns + the index.
"""
from alembic import op
import sqlalchemy as sa


revision = "0036_phase15_recommendation_closure"
down_revision = "0035_phase15_recommendation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        # Plain nullable integer columns first (SQLite-safe; no inline FK).
        batch_op.add_column(
            sa.Column("sales_task_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("opportunity_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True)
        )
        # Indexes for the join keys.
        batch_op.create_index(
            "ix_recommendations_sales_task_id", ["sales_task_id"]
        )
        batch_op.create_index(
            "ix_recommendations_opportunity_id", ["opportunity_id"]
        )
        # Foreign keys (SET NULL) — batch mode rewrites the table on SQLite so
        # these are applied safely across both SQLite and Postgres.
        batch_op.create_foreign_key(
            "fk_recommendations_sales_task_id",
            "sales_tasks",
            ["sales_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_recommendations_opportunity_id",
            "opportunities",
            ["opportunity_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_constraint(
            "fk_recommendations_opportunity_id", type_="foreignkey"
        )
        batch_op.drop_index("ix_recommendations_opportunity_id")
        batch_op.drop_column("opportunity_id")
        batch_op.drop_constraint(
            "fk_recommendations_sales_task_id", type_="foreignkey"
        )
        batch_op.drop_index("ix_recommendations_sales_task_id")
        batch_op.drop_column("sales_task_id")
        batch_op.drop_column("expired_at")
