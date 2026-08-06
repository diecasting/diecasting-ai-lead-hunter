"""Phase 7 — Quora + SEO Authority Engine ORM models.

Four tables back the authority engine:

* ``quora_questions``     — discovered / manually added Quora questions moving
                            through the content workflow.
* ``content_articles``    — the curated industrial content database (Markdown)
                            that answers are grounded in.
* ``quora_answers``       — AI-generated (or manual) answers to a question.
* ``blog_posts``          — SEO blog posts produced by reusing an answer or a
                            content article (the "SEO blog reuse pipeline").

All timestamps are UTC. New tables are created by Alembic migration
``0019_phase7_quora_seo_authority`` (and by ``create_all`` on SQLite dev).
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Question lifecycle (mirrors the discovery pipeline's explicit state machine).
QUESTION_NEW = "new"
QUESTION_RESEARCHED = "researched"
QUESTION_DRAFTED = "drafted"
QUESTION_ANSWERED = "answered"
QUESTION_PUBLISHED = "published"
QUESTION_STATUSES = [
    QUESTION_NEW,
    QUESTION_RESEARCHED,
    QUESTION_DRAFTED,
    QUESTION_ANSWERED,
    QUESTION_PUBLISHED,
]

# Answer lifecycle.
ANSWER_DRAFT = "draft"
ANSWER_REVIEW = "review"
ANSWER_PUBLISHED = "published"
ANSWER_EXPORTED = "exported"
ANSWER_STATUSES = [
    ANSWER_DRAFT,
    ANSWER_REVIEW,
    ANSWER_PUBLISHED,
    ANSWER_EXPORTED,
]

# Blog post lifecycle.
BLOG_DRAFT = "draft"
BLOG_PUBLISHED = "published"
BLOG_STATUSES = [BLOG_DRAFT, BLOG_PUBLISHED]


class QuoraQuestion(Base):
    """A Quora question tracked by the authority engine."""

    __tablename__ = "quora_questions"

    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    quora_url = Column(String(1024), nullable=True, index=True)
    topic = Column(String(160), nullable=True, index=True)
    tags = Column(Text, nullable=True)  # comma-joined
    source = Column(
        String(120), nullable=False, default="manual",
        server_default="manual", index=True,
    )  # manual | search
    status = Column(
        String(30), nullable=False, default=QUESTION_NEW,
        server_default=QUESTION_NEW, index=True,
    )
    # Chosen / published answer id (plain int — no FK, avoids circular DDL).
    answer_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    answers = relationship(
        "QuoraAnswer", backref="question", lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QuoraQuestion id={self.id} status={self.status!r}>"


class ContentArticle(Base):
    """A curated industrial content article (Markdown) for the content DB."""

    __tablename__ = "content_articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    body_markdown = Column(Text, nullable=False)
    topic = Column(String(160), nullable=True, index=True)
    tags = Column(Text, nullable=True)  # comma-joined
    source = Column(
        String(120), nullable=False, default="manual",
        server_default="manual",
    )  # manual | curated
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentArticle id={self.id} title={self.title!r}>"


class QuoraAnswer(Base):
    """An answer (generated or manual) attached to a Quora question."""

    __tablename__ = "quora_answers"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(
        Integer, ForeignKey("quora_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_markdown = Column(Text, nullable=True)
    status = Column(
        String(30), nullable=False, default=ANSWER_DRAFT,
        server_default=ANSWER_DRAFT, index=True,
    )
    quality_score = Column(Integer, nullable=True)  # 0-100
    source_type = Column(
        String(30), nullable=False, default="generated",
        server_default="generated",
    )  # generated | manual
    used_content_ids = Column(Text, nullable=True)  # comma-joined ContentArticle ids
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QuoraAnswer id={self.id} status={self.status!r}>"


class BlogPost(Base):
    """An SEO blog post produced by the reuse pipeline."""

    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=True, index=True)
    meta_title = Column(String(255), nullable=True)
    meta_description = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)  # comma-joined
    body_markdown = Column(Text, nullable=True)
    source_type = Column(
        String(30), nullable=False, default="answer",
        server_default="answer",
    )  # answer | content
    source_id = Column(Integer, nullable=True)
    status = Column(
        String(30), nullable=False, default=BLOG_DRAFT,
        server_default=BLOG_DRAFT, index=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BlogPost id={self.id} slug={self.slug!r}>"
