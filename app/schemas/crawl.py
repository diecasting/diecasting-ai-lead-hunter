"""Pydantic schemas for the crawl API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CrawlRunRequest(BaseModel):
    """Trigger crawling of pending tasks, or a single lead if ``lead_id`` given."""

    lead_id: Optional[int] = None
    limit: int = 50
    max_retries: Optional[int] = None


class CrawlTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: Optional[int] = None
    domain: Optional[str] = None
    url: Optional[str] = None
    status: str
    retry_count: int
    max_retries: int
    emails: Optional[str] = None
    pages_crawled: int
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CrawlRunResult(BaseModel):
    tasks_processed: int
    succeeded: int
    failed: int
    skipped: int
    details: List[int] = []
