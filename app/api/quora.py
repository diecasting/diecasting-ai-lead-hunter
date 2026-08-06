"""Phase 7 — Quora + SEO Authority Engine API.

Two routers (both mounted in ``app.main``):

* ``quora_router`` (prefix ``/quora``): question discovery + workflow, the
  industrial content database, AI answer generation, and answer export.
* ``seo_router``  (prefix ``/seo``):  the SEO blog reuse pipeline (list /
  detail / export blog posts produced from answers or content).
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.quora import (
    ANSWER_DRAFT,
    BlogPost,
    ContentArticle,
    QuoraAnswer,
    QuoraQuestion,
    QUESTION_DRAFTED,
)
from app.quora import crud as qcrud
from app.quora import discovery as discovery_mod
from app.quora import content_db as content_mod
from app.quora import answer_generator as answer_mod
from app.quora import workflow as workflow_mod
from app.quora import export as export_mod
from app.quora import seo as seo_mod

quora_router = APIRouter(prefix="/quora", tags=["quora"])
seo_router = APIRouter(prefix="/seo", tags=["seo"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class DiscoverRequest(BaseModel):
    keyword: str
    limit: int = 20


class CreateQuestionRequest(BaseModel):
    question_text: str
    quora_url: Optional[str] = None
    topic: Optional[str] = None
    tags: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    status: str


class CreateContentRequest(BaseModel):
    title: str
    body_markdown: str
    topic: Optional[str] = None
    tags: Optional[str] = None


class GenerateAnswerRequest(BaseModel):
    use_llm: bool = True


class QuestionRead(BaseModel):
    id: int
    question_text: str
    quora_url: Optional[str] = None
    topic: Optional[str] = None
    tags: Optional[str] = None
    source: str = "manual"
    status: str = "new"
    answer_id: Optional[int] = None
    answer_count: int = 0
    created_at: Optional[str] = None


class ContentRead(BaseModel):
    id: int
    title: str
    body_markdown: str
    topic: Optional[str] = None
    tags: Optional[str] = None
    source: str = "manual"
    created_at: Optional[str] = None


class AnswerRead(BaseModel):
    id: int
    question_id: int
    question_text: str
    content_markdown: Optional[str] = None
    status: str = "draft"
    quality_score: Optional[int] = None
    source_type: str = "generated"
    used_content_ids: Optional[str] = None
    created_at: Optional[str] = None


class BlogRead(BaseModel):
    id: int
    title: str
    slug: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    keywords: Optional[str] = None
    body_markdown: Optional[str] = None
    source_type: str = "answer"
    source_id: Optional[int] = None
    status: str = "draft"
    created_at: Optional[str] = None


class ExportResult(BaseModel):
    path: str
    filename: str
    markdown: str


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------
def _question_to_read(row: QuoraQuestion) -> QuestionRead:
    return QuestionRead(
        id=row.id,
        question_text=row.question_text,
        quora_url=row.quora_url,
        topic=row.topic,
        tags=row.tags,
        source=row.source,
        status=row.status,
        answer_id=row.answer_id,
        answer_count=len(row.answers) if row.answers else 0,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _content_to_read(row: ContentArticle) -> ContentRead:
    return ContentRead(
        id=row.id,
        title=row.title,
        body_markdown=row.body_markdown,
        topic=row.topic,
        tags=row.tags,
        source=row.source,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _answer_to_read(row: QuoraAnswer) -> AnswerRead:
    return AnswerRead(
        id=row.id,
        question_id=row.question_id,
        question_text=row.question.question_text if row.question else "",
        content_markdown=row.content_markdown,
        status=row.status,
        quality_score=row.quality_score,
        source_type=row.source_type,
        used_content_ids=row.used_content_ids,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _blog_to_read(row: BlogPost) -> BlogRead:
    return BlogRead(
        id=row.id,
        title=row.title,
        slug=row.slug,
        meta_title=row.meta_title,
        meta_description=row.meta_description,
        keywords=row.keywords,
        body_markdown=row.body_markdown,
        source_type=row.source_type,
        source_id=row.source_id,
        status=row.status,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


# ---------------------------------------------------------------------------
# Quora questions: discovery + workflow
# ---------------------------------------------------------------------------
@quora_router.post("/questions/discover", response_model=dict, status_code=201)
def discover_questions(payload: DiscoverRequest, db: Session = Depends(get_db)):
    """Discover Quora questions for a keyword and persist new ones.

    New questions are de-duplicated by ``quora_url``. When the search provider
    is unavailable (no key / no network) this returns ``created: 0`` instead of
    erroring, so the endpoint is safe in dry-run / sandbox environments.
    """
    keyword = (payload.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword is required")

    candidates = discovery_mod.discover_questions(keyword, limit=payload.limit)
    created: List[QuoraQuestion] = []
    for c in candidates:
        url = c.get("quora_url")
        if url and qcrud.get_question_by_url(db, url):
            continue
        q = qcrud.create_question(
            db,
            question_text=c["question_text"],
            quora_url=url,
            topic=c.get("topic") or keyword,
            tags=c.get("tags"),
            source="search",
        )
        created.append(q)
    return {
        "keyword": keyword,
        "discovered": len(candidates),
        "created": len(created),
        "questions": [_question_to_read(q) for q in created],
    }


@quora_router.get("/questions", response_model=List[QuestionRead])
def list_questions(
    status: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List tracked Quora questions (newest first), optionally filtered."""
    rows = qcrud.list_questions(db, status=status, topic=topic, limit=limit)
    return [_question_to_read(r) for r in rows]


@quora_router.post("/questions", response_model=QuestionRead, status_code=201)
def create_question(payload: CreateQuestionRequest, db: Session = Depends(get_db)):
    """Manually add a Quora question to the workflow."""
    text = (payload.question_text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="question_text is required")
    row = qcrud.create_question(
        db,
        question_text=text,
        quora_url=(payload.quora_url or "").strip() or None,
        topic=(payload.topic or "").strip() or None,
        tags=(payload.tags or "").strip() or None,
        source="manual",
    )
    return _question_to_read(row)


@quora_router.get("/questions/{question_id}", response_model=QuestionRead)
def get_question(question_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_question(db, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return _question_to_read(row)


@quora_router.patch("/questions/{question_id}/status", response_model=QuestionRead)
def update_question_status(
    question_id: int, payload: StatusUpdateRequest, db: Session = Depends(get_db)
):
    """Advance a question through its workflow (validated transition)."""
    row = qcrud.get_question(db, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")
    try:
        target = workflow_mod.validate_question_transition(row.status, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    updated = qcrud.update_question_status(db, row, target)
    return _question_to_read(updated)


@quora_router.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_question(db, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")
    qcrud.delete_question(db, row)


# ---------------------------------------------------------------------------
# Industrial content database
# ---------------------------------------------------------------------------
@quora_router.get("/content", response_model=List[ContentRead])
def list_content(
    topic: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)
):
    """List curated industrial content articles."""
    rows = qcrud.list_articles(db, topic=topic, limit=limit)
    return [_content_to_read(r) for r in rows]


@quora_router.post("/content", response_model=ContentRead, status_code=201)
def create_content(payload: CreateContentRequest, db: Session = Depends(get_db)):
    """Add an article to the industrial content database."""
    title = (payload.title or "").strip()
    body = (payload.body_markdown or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    if not body:
        raise HTTPException(status_code=422, detail="body_markdown is required")
    row = qcrud.create_article(
        db,
        title=title,
        body_markdown=body,
        topic=(payload.topic or "").strip() or None,
        tags=(payload.tags or "").strip() or None,
        source="manual",
    )
    return _content_to_read(row)


@quora_router.get("/content/{content_id}", response_model=ContentRead)
def get_content(content_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_article(db, content_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Content article not found")
    return _content_to_read(row)


@quora_router.delete("/content/{content_id}", status_code=204)
def delete_content(content_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_article(db, content_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Content article not found")
    qcrud.delete_article(db, row)


# ---------------------------------------------------------------------------
# AI answer generation + answer workflow
# ---------------------------------------------------------------------------
@quora_router.post("/questions/{question_id}/generate-answer", response_model=AnswerRead, status_code=201)
def generate_answer(question_id: int, payload: GenerateAnswerRequest, db: Session = Depends(get_db)):
    """Generate a grounded answer for a question from the content database.

    Ranks the most on-topic curated articles, then produces a Markdown answer
    (AI when OPENAI_API_KEY is set, else a deterministic template render) and
    stores it as a draft ``QuoraAnswer``.
    """
    question = qcrud.get_question(db, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    matches = content_mod.rank_content_for_query(
        db, question.question_text, topic=question.topic, limit=5
    )
    result = answer_mod.generate_answer(
        question, content_articles=matches, use_llm=payload.use_llm
    )
    answer = qcrud.create_answer(
        db,
        question_id=question.id,
        content_markdown=result["content_markdown"],
        status=ANSWER_DRAFT,
        quality_score=result["quality_score"],
        source_type="generated",
        used_content_ids=",".join(str(i) for i in result["used_content_ids"]),
    )
    # Drafting is always a valid forward step for the question.
    if question.status in ("new", "researched"):
        qcrud.update_question_status(db, question, QUESTION_DRAFTED)
    db.refresh(answer)
    return _answer_to_read(answer)


@quora_router.get("/answers", response_model=List[AnswerRead])
def list_answers(
    question_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    rows = qcrud.list_answers(db, question_id=question_id, status=status, limit=limit)
    return [_answer_to_read(r) for r in rows]


@quora_router.get("/answers/{answer_id}", response_model=AnswerRead)
def get_answer(answer_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_answer(db, answer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return _answer_to_read(row)


@quora_router.patch("/answers/{answer_id}/status", response_model=AnswerRead)
def update_answer_status(
    answer_id: int, payload: StatusUpdateRequest, db: Session = Depends(get_db)
):
    row = qcrud.get_answer(db, answer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    try:
        target = workflow_mod.validate_answer_transition(row.status, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    updated = qcrud.update_answer(db, row, status=target)
    return _answer_to_read(updated)


@quora_router.post("/answers/{answer_id}/export-markdown", response_model=ExportResult)
def export_answer(answer_id: int, db: Session = Depends(get_db)):
    """Export a Quora answer to a Markdown file and return its content."""
    answer = qcrud.get_answer(db, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    question = qcrud.get_question(db, answer.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Parent question not found")
    md = export_mod.export_answer_markdown(question, answer)
    path = export_mod.write_markdown_file(
        f"quora-answer-{answer.id}", md, base_dir=settings.quora_export_dir
    )
    return ExportResult(
        path=path, filename=os.path.basename(path), markdown=md
    )


# ---------------------------------------------------------------------------
# SEO blog reuse pipeline (entry points from quora side)
# ---------------------------------------------------------------------------
@quora_router.post("/answers/{answer_id}/reuse-blog", response_model=BlogRead, status_code=201)
def reuse_answer_blog(answer_id: int, db: Session = Depends(get_db)):
    """Reuse a Quora answer as an SEO blog post (advances both workflows)."""
    answer = qcrud.get_answer(db, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    question = qcrud.get_question(db, answer.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Parent question not found")
    blog = seo_mod.reuse_answer_as_blog(db, answer, question)
    return _blog_to_read(blog)


@quora_router.post("/content/{content_id}/reuse-blog", response_model=BlogRead, status_code=201)
def reuse_content_blog(content_id: int, db: Session = Depends(get_db)):
    """Reuse a curated content article as an SEO blog post."""
    article = qcrud.get_article(db, content_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Content article not found")
    blog = seo_mod.reuse_content_as_blog(db, article)
    return _blog_to_read(blog)


# ---------------------------------------------------------------------------
# SEO blog posts (read / export / delete)
# ---------------------------------------------------------------------------
@seo_router.get("/blog", response_model=List[BlogRead])
def list_blogs(
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    rows = qcrud.list_blogs(db, status=status, source_type=source_type, limit=limit)
    return [_blog_to_read(r) for r in rows]


@seo_router.get("/blog/{blog_id}", response_model=BlogRead)
def get_blog(blog_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_blog(db, blog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return _blog_to_read(row)


@seo_router.post("/blog/{blog_id}/export-markdown", response_model=ExportResult)
def export_blog(blog_id: int, db: Session = Depends(get_db)):
    """Export an SEO blog post to a Markdown file and return its content."""
    blog = qcrud.get_blog(db, blog_id)
    if blog is None:
        raise HTTPException(status_code=404, detail="Blog post not found")
    md = export_mod.export_blog_markdown(blog)
    path = export_mod.write_markdown_file(
        f"seo-blog-{blog.id}-{blog.slug or 'post'}", md, base_dir=settings.seo_blog_dir
    )
    return ExportResult(path=path, filename=os.path.basename(path), markdown=md)


@seo_router.delete("/blog/{blog_id}", status_code=204)
def delete_blog(blog_id: int, db: Session = Depends(get_db)):
    row = qcrud.get_blog(db, blog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Blog post not found")
    qcrud.delete_blog(db, row)
