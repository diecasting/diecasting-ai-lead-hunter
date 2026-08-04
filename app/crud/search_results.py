"""CRUD operations for SearchResult."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.search_result import SearchResult


def create(
    db: Session,
    *,
    keyword: str,
    url: str,
    title: Optional[str] = None,
    snippet: Optional[str] = None,
    country: Optional[str] = None,
    rank: Optional[int] = None,
) -> SearchResult:
    obj = SearchResult(
        keyword=keyword,
        url=url,
        title=title,
        snippet=snippet,
        country=country,
        rank=rank,
    )
    db.add(obj)
    db.flush()
    return obj


def get_multi(
    db: Session,
    *,
    keyword: Optional[str] = None,
    country: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
) -> List[SearchResult]:
    query = db.query(SearchResult)
    if keyword:
        query = query.filter(SearchResult.keyword == keyword)
    if country:
        query = query.filter(SearchResult.country == country)
    return (
        query.order_by(SearchResult.id.desc()).offset(skip).limit(limit).all()
    )
