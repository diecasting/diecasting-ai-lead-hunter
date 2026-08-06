"""CRUD helpers for the Phase 7 Quora + SEO Authority Engine.

Thin, explicit functions (no generic ORM magic) matching the rest of the
codebase' session-first style. Every function takes the active ``Session``.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.quora import (
    BlogPost,
    ContentArticle,
    QuoraAnswer,
    QuoraQuestion,
)


# ---------------------------------------------------------------------------
# QuoraQuestion
# ---------------------------------------------------------------------------
def create_question(
    db: Session,
    question_text: str,
    quora_url: Optional[str] = None,
    topic: Optional[str] = None,
    tags: Optional[str] = None,
    source: str = "manual",
    status: str = "new",
) -> QuoraQuestion:
    row = QuoraQuestion(
        question_text=question_text,
        quora_url=quora_url,
        topic=topic,
        tags=tags,
        source=source,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_question(db: Session, question_id: int) -> Optional[QuoraQuestion]:
    return db.query(QuoraQuestion).filter(QuoraQuestion.id == question_id).first()


def get_question_by_url(db: Session, quora_url: str) -> Optional[QuoraQuestion]:
    if not quora_url:
        return None
    return (
        db.query(QuoraQuestion)
        .filter(QuoraQuestion.quora_url == quora_url)
        .first()
    )


def list_questions(
    db: Session,
    status: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 100,
) -> List[QuoraQuestion]:
    q = db.query(QuoraQuestion)
    if status:
        q = q.filter(QuoraQuestion.status == status)
    if topic:
        q = q.filter(QuoraQuestion.topic == topic)
    return q.order_by(QuoraQuestion.created_at.desc()).limit(limit).all()


def update_question_status(db: Session, row: QuoraQuestion, status: str) -> QuoraQuestion:
    row.status = status
    db.commit()
    db.refresh(row)
    return row


def set_question_answer(db: Session, row: QuoraQuestion, answer_id: Optional[int]) -> QuoraQuestion:
    row.answer_id = answer_id
    db.commit()
    db.refresh(row)
    return row


def delete_question(db: Session, row: QuoraQuestion) -> None:
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# ContentArticle (industrial content database)
# ---------------------------------------------------------------------------
def create_article(
    db: Session,
    title: str,
    body_markdown: str,
    topic: Optional[str] = None,
    tags: Optional[str] = None,
    source: str = "manual",
) -> ContentArticle:
    row = ContentArticle(
        title=title,
        body_markdown=body_markdown,
        topic=topic,
        tags=tags,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_article(db: Session, article_id: int) -> Optional[ContentArticle]:
    return db.query(ContentArticle).filter(ContentArticle.id == article_id).first()


def list_articles(
    db: Session,
    topic: Optional[str] = None,
    limit: int = 100,
) -> List[ContentArticle]:
    q = db.query(ContentArticle)
    if topic:
        q = q.filter(ContentArticle.topic == topic)
    return q.order_by(ContentArticle.created_at.desc()).limit(limit).all()


def delete_article(db: Session, row: ContentArticle) -> None:
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# QuoraAnswer
# ---------------------------------------------------------------------------
def create_answer(
    db: Session,
    question_id: int,
    content_markdown: Optional[str] = None,
    status: str = "draft",
    quality_score: Optional[int] = None,
    source_type: str = "generated",
    used_content_ids: Optional[str] = None,
) -> QuoraAnswer:
    row = QuoraAnswer(
        question_id=question_id,
        content_markdown=content_markdown,
        status=status,
        quality_score=quality_score,
        source_type=source_type,
        used_content_ids=used_content_ids,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_answer(db: Session, answer_id: int) -> Optional[QuoraAnswer]:
    return db.query(QuoraAnswer).filter(QuoraAnswer.id == answer_id).first()


def list_answers(
    db: Session,
    question_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[QuoraAnswer]:
    q = db.query(QuoraAnswer)
    if question_id is not None:
        q = q.filter(QuoraAnswer.question_id == question_id)
    if status:
        q = q.filter(QuoraAnswer.status == status)
    return q.order_by(QuoraAnswer.created_at.desc()).limit(limit).all()


def update_answer(
    db: Session,
    row: QuoraAnswer,
    content_markdown: Optional[str] = None,
    status: Optional[str] = None,
    quality_score: Optional[int] = None,
) -> QuoraAnswer:
    if content_markdown is not None:
        row.content_markdown = content_markdown
    if status is not None:
        row.status = status
    if quality_score is not None:
        row.quality_score = quality_score
    db.commit()
    db.refresh(row)
    return row


def delete_answer(db: Session, row: QuoraAnswer) -> None:
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# BlogPost (SEO reuse pipeline)
# ---------------------------------------------------------------------------
def create_blog(
    db: Session,
    title: str,
    slug: Optional[str] = None,
    meta_title: Optional[str] = None,
    meta_description: Optional[str] = None,
    keywords: Optional[str] = None,
    body_markdown: Optional[str] = None,
    source_type: str = "answer",
    source_id: Optional[int] = None,
    status: str = "draft",
) -> BlogPost:
    row = BlogPost(
        title=title,
        slug=slug,
        meta_title=meta_title,
        meta_description=meta_description,
        keywords=keywords,
        body_markdown=body_markdown,
        source_type=source_type,
        source_id=source_id,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_blog(db: Session, blog_id: int) -> Optional[BlogPost]:
    return db.query(BlogPost).filter(BlogPost.id == blog_id).first()


def get_blog_by_slug(db: Session, slug: str) -> Optional[BlogPost]:
    if not slug:
        return None
    return db.query(BlogPost).filter(BlogPost.slug == slug).first()


def list_blogs(
    db: Session,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
) -> List[BlogPost]:
    q = db.query(BlogPost)
    if status:
        q = q.filter(BlogPost.status == status)
    if source_type:
        q = q.filter(BlogPost.source_type == source_type)
    return q.order_by(BlogPost.created_at.desc()).limit(limit).all()


def delete_blog(db: Session, row: BlogPost) -> None:
    db.delete(row)
    db.commit()
