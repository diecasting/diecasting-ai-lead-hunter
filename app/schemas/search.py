"""Pydantic schemas for the search API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SearchRunRequest(BaseModel):
    keyword: str
    country: str = "us"
    max_results: int = 20
    exclude_directories: bool = True
    keep_only_manufacturers: bool = False


class SearchResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    country: Optional[str] = None
    rank: Optional[int] = None
    created_at: datetime
