"""Search service: run a SERP search, filter, and persist results as leads.

``SearchService.run_search``:
1. asks the configured provider for organic results,
2. applies the directory / manufacturer filters,
3. stores each surviving result in ``search_results``,
4. creates a ``company_leads`` row (deduplicated by homepage) with
   ``crawl_status='pending'`` and a linked ``crawl_tasks`` row.
"""
import json
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.crud import ai_analysis as ai_analysis_crud
from app.crud import crawl_tasks as crawl_tasks_crud
from app.crud import leads as leads_crud
from app.crud import search_results as search_results_crud
from app.models.crawl_task import CrawlTask
from app.models.lead import CompanyLead
from app.models.search_result import SearchResult
from app.search.base import BaseSearchProvider, SearchResult as SearchResultData
from app.search.filters import filter_results
from app.search.google import GoogleProvider


def _homepage(url: str) -> str:
    """Best-effort homepage (scheme + registered host) for a URL."""
    try:
        parts = urlparse(url)
        scheme = parts.scheme or "https"
        host = parts.netloc or parts.path.split("/")[0]
        if not host:
            return url
        return f"{scheme}://{host}"
    except Exception:
        return url


def _domain(url: str) -> Optional[str]:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return None


class SearchService:
    def __init__(self, provider: Optional[BaseSearchProvider] = None):
        self.provider = provider or GoogleProvider()

    def search_urls(
        self, keyword: str, country: str = "us", max_results: int = 50
    ) -> List[str]:
        """Raw candidate homepage URLs for a keyword — no persistence.

        Used by the Phase 5 Stage 2 batch discovery queue to resolve prospect
        sites before the website-analysis pipeline runs. Results are filtered
        (directories excluded) and deduplicated to homepage URLs.
        """
        raw = self.provider.search(keyword, country=country, max_results=max_results)
        filtered = filter_results(raw)
        urls: List[str] = []
        seen: set = set()
        for r in filtered:
            home = _homepage(r.url)
            if home and home not in seen:
                seen.add(home)
                urls.append(home)
        return urls

    def run_search(
        self,
        db: Session,
        keyword: str,
        country: str = "us",
        max_results: int = 20,
        exclude_directories: bool = True,
        keep_only_manufacturers: bool = False,
    ) -> dict:
        raw = self.provider.search(keyword, country=country, max_results=max_results)
        filtered = filter_results(
            raw,
            exclude_directories=exclude_directories,
            keep_only_manufacturers=keep_only_manufacturers,
        )

        results_saved = 0
        leads_created = 0
        leads_skipped = 0
        created_lead_ids: List[int] = []

        for r in filtered:
            # 1. persist the raw search hit
            sr = search_results_crud.create(
                db,
                keyword=r.keyword,
                url=r.url,
                title=r.title,
                snippet=r.snippet,
                country=r.country,
                rank=r.rank,
            )
            results_saved += 1

            # 2. derive a lead (dedup by homepage)
            homepage = _homepage(r.url)
            domain = _domain(homepage)
            existing = leads_crud.get_by_website(db, homepage)
            if existing:
                leads_skipped += 1
                continue
            lead = leads_crud.create(
                db,
                name=(r.title or domain or homepage)[:255],
                website=homepage,
                domain=domain,
                country=country.upper() if country else None,
                industry="Die casting",
                source="google_search",
                lead_source="search",
                crawl_status="pending",
            )
            # 3. create a crawl task for the new lead
            crawl_tasks_crud.create(
                db,
                lead_id=lead.id,
                domain=domain,
                url=homepage,
                status="pending",
            )
            leads_created += 1
            created_lead_ids.append(lead.id)

        db.commit()
        return {
            "keyword": keyword,
            "country": country,
            "raw_results": len(raw),
            "results_saved": results_saved,
            "leads_created": leads_created,
            "leads_skipped": leads_skipped,
            "created_lead_ids": created_lead_ids,
        }
