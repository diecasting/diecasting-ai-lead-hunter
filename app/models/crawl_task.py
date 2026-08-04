"""CrawlTask ORM model — tracks the crawling of a single company website.

A crawl task is created whenever a lead is discovered (from search, import,
etc.). The crawler picks up ``pending`` tasks, fetches the company's pages
(homepage / about / products / industries / contact / sitemap), extracts
e-mails, and records the outcome. A retry mechanism bumps ``retry_count`` on
failure and only marks the task ``failed`` once ``max_retries`` is exceeded.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

from app.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class CrawlTask(Base):
    __tablename__ = "crawl_tasks"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id"), nullable=True, index=True
    )
    domain = Column(String(255), nullable=True, index=True)
    url = Column(String(1024), nullable=True)  # homepage used as crawl entry point

    # status: pending | running | success | failed
    status = Column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_retries = Column(Integer, nullable=False, default=3, server_default="3")

    emails = Column(Text, nullable=True)            # JSON-encoded list[str]
    pages_crawled = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CrawlTask id={self.id} domain={self.domain!r} status={self.status!r}>"
