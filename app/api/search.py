"""Search API routes (Phase 2.1 / 2.2).

Endpoints
---------
* ``POST /search``   — run a Google SERP search for a keyword, filter and persist.
* ``GET  /search/results`` — list stored ``search_results`` rows.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.crud import search_results as crud
from app.database import get_db
from app.schemas.search import SearchResultRead
from app.search.service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    keyword: str
    limit: int = 50
    country: str = "us"


@router.post("", response_model=dict)
def run_search(payload: SearchRequest, db: Session = Depends(get_db)):
    """Run a Google SERP search, apply directory/manufacturer filters, persist."""
    try:
        report = SearchService().run_search(
            db,
            keyword=payload.keyword,
            country=payload.country,
            max_results=payload.limit,
        )
    except Exception as exc:  # pragma: no cover - depends on network/browser
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")
    return report


@router.get("/results", response_model=List[SearchResultRead])
def list_results(
    db: Session = Depends(get_db),
    keyword: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    return crud.get_multi(db, keyword=keyword, country=country, skip=skip, limit=limit)


@router.get("/status", response_model=dict)
def search_status():
    """Return the active search provider configuration (no secrets).

    ``provider`` is ``serpapi`` when ``SEARCH_PROVIDER=serpapi`` (configured
    only when ``SERPAPI_KEY`` is present), otherwise the Google fallback.
    """
    from app.config import settings

    name = (settings.search_provider or "google").strip().lower()
    provider = "serpapi" if name == "serpapi" else "google"
    configured = bool(settings.serpapi_key) if provider == "serpapi" else True
    return {
        "provider": provider,
        "configured": configured,
        "serpapi_key_set": bool(settings.serpapi_key),
    }
