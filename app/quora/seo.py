"""SEO blog reuse pipeline for the Phase 7 Authority Engine.

Turns a published Quora answer (or a curated content article) into an SEO-ready
blog post: derives a URL slug, a meta title / description / keywords, and keeps
a back-link to the source (``source_type`` / ``source_id``). This is the bridge
from Q&A authority building to owned-media SEO.
"""
import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.quora import (
    ANSWER_PUBLISHED,
    BlogPost,
    ContentArticle,
    QuoraAnswer,
    QuoraQuestion,
    QUESTION_ANSWERED,
    QUESTION_PUBLISHED,
)
from app.quora import crud as qcrud


def generate_slug(title: str) -> str:
    """Convert a title into a URL-safe slug."""
    s = (title or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = "-".join(filter(None, s.split("-")))
    return s or "post"


def _plain(body: str, limit: int) -> str:
    """Strip Markdown to a short plain-text excerpt."""
    text = re.sub(r"[#>*_`\-]+", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip() + "…"
    return text


def derive_meta(
    title: str,
    body_markdown: str,
    topic: Optional[str],
    tags: Optional[str],
) -> Tuple[str, str, str]:
    """Derive (meta_title, meta_description, keywords) for a blog post."""
    meta_title = (title or "").strip()[:70] or "Industrial manufacturing insights"
    meta_description = _plain(body_markdown or "", 155)
    keywords_parts = []
    if topic:
        keywords_parts.append(topic.strip())
    if tags:
        keywords_parts.extend([t.strip() for t in tags.split(",") if t.strip()])
    keywords = ", ".join(dict.fromkeys(keywords_parts))  # dedupe, keep order
    return meta_title, meta_description, keywords


def reuse_answer_as_blog(
    db: Session, answer: QuoraAnswer, question: QuoraQuestion
) -> BlogPost:
    """Create an SEO blog post from a Quora answer and advance its workflow."""
    title = question.question_text.strip()
    slug = generate_slug(title)
    meta_title, meta_description, keywords = derive_meta(
        title, answer.content_markdown or "", question.topic, question.tags
    )
    blog = qcrud.create_blog(
        db,
        title=title,
        slug=slug,
        meta_title=meta_title,
        meta_description=meta_description,
        keywords=keywords,
        body_markdown=answer.content_markdown,
        source_type="answer",
        source_id=answer.id,
        status="draft",
    )
    # Advance the source workflow: the answer is now published, and the
    # question is marked answered / published with this as the chosen answer.
    answer.status = ANSWER_PUBLISHED
    db.add(answer)
    question.status = QUESTION_PUBLISHED
    question.answer_id = answer.id
    db.add(question)
    db.commit()
    db.refresh(blog)
    return blog


def reuse_content_as_blog(db: Session, article: ContentArticle) -> BlogPost:
    """Create an SEO blog post directly from a curated content article."""
    title = article.title.strip()
    slug = generate_slug(title)
    meta_title, meta_description, keywords = derive_meta(
        title, article.body_markdown, article.topic, article.tags
    )
    blog = qcrud.create_blog(
        db,
        title=title,
        slug=slug,
        meta_title=meta_title,
        meta_description=meta_description,
        keywords=keywords,
        body_markdown=article.body_markdown,
        source_type="content",
        source_id=article.id,
        status="draft",
    )
    return blog
