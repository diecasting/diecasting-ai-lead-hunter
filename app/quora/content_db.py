"""Industrial content database for the Phase 7 Authority Engine.

Wraps :mod:`app.quora.crud` with relevance ranking so the answer generator can
pull the most on-topic curated articles for a given Quora question. Matching
uses topic equality, tag overlap, and keyword presence in the title/body —
no embeddings required, deterministic and offline-friendly.
"""
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.quora import ContentArticle
from app.quora import crud as qcrud


def _normalise_tags(tags: Optional[str]) -> List[str]:
    if not tags:
        return []
    return [t.strip().lower() for t in tags.split(",") if t.strip()]


def _tokenize(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def rank_content_for_query(
    db: Session,
    query: str,
    *,
    topic: Optional[str] = None,
    limit: int = 5,
) -> List[ContentArticle]:
    """Rank content articles by relevance to ``query`` (+ optional topic).

    Scoring (deterministic):
      +40  topic exactly matches the query topic
      +8   per overlapping tag (cap +24)
      +1   per query token found in title / body / tags (cap +30)
    Returns the top ``limit`` articles (ties broken by created_at desc).
    """
    articles = qcrud.list_articles(db)
    query_tokens = _tokenize(query)
    topic_norm = (topic or "").strip().lower()

    scored = []
    for a in articles:
        score = 0
        a_tags = _normalise_tags(a.tags)
        if topic_norm and a.topic and a.topic.strip().lower() == topic_norm:
            score += 40
        overlap = len(set(a_tags) & query_tokens)
        score += min(overlap, 3) * 8
        haystack = f"{a.title} {a.body_markdown} {a.tags or ''}".lower()
        hits = sum(1 for tok in query_tokens if tok in haystack)
        score += min(hits, 30)
        scored.append((score, a))

    scored.sort(key=lambda x: (x[0], x[1].created_at or 0), reverse=True)
    return [a for _, a in scored[:limit]]


def search_content(
    db: Session,
    query: str,
    *,
    topic: Optional[str] = None,
    limit: int = 50,
) -> List[ContentArticle]:
    """Free-text search over the content DB (title/body/tags substring)."""
    q = db.query(ContentArticle)
    if topic:
        q = q.filter(ContentArticle.topic == topic)
    if query:
        like = f"%{query}%"
        q = q.filter(
            ContentArticle.title.ilike(like)
            | ContentArticle.body_markdown.ilike(like)
            | ContentArticle.tags.ilike(like)
        )
    return q.order_by(ContentArticle.created_at.desc()).limit(limit).all()
