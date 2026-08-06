"""Phase 7: Quora + SEO Authority Engine tables

Revision ID: 0019_phase7_quora_seo_authority
Revises: 0018_phase65_lead_email_verification
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_phase7_quora_seo_authority"
down_revision = "0018_phase65_lead_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quora_questions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("quora_url", sa.String(length=1024), nullable=True),
        sa.Column("topic", sa.String(length=160), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(length=120), nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False,
            server_default="new",
        ),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_quora_questions_quora_url", "quora_questions", ["quora_url"])
    op.create_index("ix_quora_questions_topic", "quora_questions", ["topic"])
    op.create_index("ix_quora_questions_source", "quora_questions", ["source"])
    op.create_index("ix_quora_questions_status", "quora_questions", ["status"])

    op.create_table(
        "content_articles",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=160), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(length=120), nullable=False,
            server_default="manual",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_articles_title", "content_articles", ["title"])
    op.create_index("ix_content_articles_topic", "content_articles", ["topic"])

    op.create_table(
        "quora_answers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "question_id", sa.Integer(), nullable=False,
        ),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False,
            server_default="draft",
        ),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column(
            "source_type", sa.String(length=30), nullable=False,
            server_default="generated",
        ),
        sa.Column("used_content_ids", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["question_id"], ["quora_questions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_quora_answers_question_id", "quora_answers", ["question_id"])
    op.create_index("ix_quora_answers_status", "quora_answers", ["status"])

    op.create_table(
        "blog_posts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("body_markdown", sa.Text(), nullable=True),
        sa.Column(
            "source_type", sa.String(length=30), nullable=False,
            server_default="answer",
        ),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False,
            server_default="draft",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_blog_posts_title", "blog_posts", ["title"])
    op.create_index("ix_blog_posts_slug", "blog_posts", ["slug"])
    op.create_index("ix_blog_posts_status", "blog_posts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_blog_posts_status", table_name="blog_posts")
    op.drop_index("ix_blog_posts_slug", table_name="blog_posts")
    op.drop_index("ix_blog_posts_title", table_name="blog_posts")
    op.drop_table("blog_posts")

    op.drop_index("ix_quora_answers_status", table_name="quora_answers")
    op.drop_index("ix_quora_answers_question_id", table_name="quora_answers")
    op.drop_table("quora_answers")

    op.drop_index("ix_content_articles_topic", table_name="content_articles")
    op.drop_index("ix_content_articles_title", table_name="content_articles")
    op.drop_table("content_articles")

    op.drop_index("ix_quora_questions_status", table_name="quora_questions")
    op.drop_index("ix_quora_questions_source", table_name="quora_questions")
    op.drop_index("ix_quora_questions_topic", table_name="quora_questions")
    op.drop_index("ix_quora_questions_quora_url", table_name="quora_questions")
    op.drop_table("quora_questions")
