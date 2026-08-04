"""SearchResult ORM model — raw Google SERP hits for a keyword.

One row per (keyword, url) discovered by the SERP search system. Directory /
marketplace / aggregator domains are filtered out before persistence, but the
raw row is kept so the pipeline and analysts can audit what was found.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

from app.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class SearchResult(Base):
    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    url = Column(String(1024), nullable=False, index=True)
    title = Column(String(512), nullable=True)
    snippet = Column(Text, nullable=True)
    country = Column(String(20), nullable=True, index=True)
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SearchResult id={self.id} keyword={self.keyword!r} url={self.url!r}>"
