"""initial schema: company_leads, search_results, crawl_tasks, ai_analysis

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=120), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_relevant", sa.Boolean(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_signals", sa.Text(), nullable=True),
        sa.Column("ai_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("casting_need_score", sa.Integer(), nullable=True),
        sa.Column("sales_priority", sa.String(length=10), nullable=True),
        sa.Column("crawl_status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("contact_emails", sa.JSON(), nullable=True),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("website_content", sa.Text(), nullable=True),
        sa.Column("crawl_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("website"),
    )
    op.create_index("ix_company_leads_name", "company_leads", ["name"])
    op.create_index("ix_company_leads_website", "company_leads", ["website"])
    op.create_index("ix_company_leads_domain", "company_leads", ["domain"])
    op.create_index("ix_company_leads_crawl_status", "company_leads", ["crawl_status"])
    op.create_index("ix_company_leads_casting_need_score", "company_leads", ["casting_need_score"])
    op.create_index("ix_company_leads_sales_priority", "company_leads", ["sales_priority"])

    op.create_table(
        "search_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=20), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_results_keyword", "search_results", ["keyword"])
    op.create_index("ix_search_results_url", "search_results", ["url"])
    op.create_index("ix_search_results_country", "search_results", ["country"])

    op.create_table(
        "crawl_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("'3'")),
        sa.Column("emails", sa.Text(), nullable=True),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_tasks_lead_id", "crawl_tasks", ["lead_id"])
    op.create_index("ix_crawl_tasks_domain", "crawl_tasks", ["domain"])
    op.create_index("ix_crawl_tasks_status", "crawl_tasks", ["status"])

    op.create_table(
        "ai_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("casting_need_score", sa.Integer(), nullable=True),
        sa.Column("sales_priority", sa.String(length=10), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("products", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("buying_signal", sa.Text(), nullable=True),
        sa.Column("recommended_contact", sa.String(length=255), nullable=True),
        sa.Column("analysis_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["lead_id"], ["company_leads.id"]),
    )
    op.create_index("ix_ai_analysis_lead_id", "ai_analysis", ["lead_id"])


def downgrade() -> None:
    op.drop_table("ai_analysis")
    op.drop_table("crawl_tasks")
    op.drop_table("search_results")
    op.drop_table("company_leads")
