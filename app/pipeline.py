"""End-to-end production lead-generation pipeline (Phase 2.5).

``run_full_pipeline`` performs, in order:
    1. read the keyword library,
    2. run Google SERP searches (per keyword / country),
    3. crawl the discovered company websites,
    4. run the AI analysis / scoring,
    5. persist everything as leads (+ search_results, crawl_tasks, ai_analysis).

The search provider and website crawler are injectable so the pipeline can be
exercised in tests without a browser or network.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.analyzer import run_analysis
from app.config import settings
from app.crawler.website_crawler import WebsiteCrawler
from app.crawler.runner import process_pending
from app.crud import leads as leads_crud
from app.search.google import GoogleProvider
from app.search.keywords import load_keywords
from app.search.service import SearchService


def run_full_pipeline(
    db: Session,
    *,
    keywords: Optional[List[str]] = None,
    country: Optional[str] = None,
    max_results: Optional[int] = None,
    search_provider=None,
    website_crawler: Optional[WebsiteCrawler] = None,
) -> dict:
    country = country or settings.search_country_default
    max_results = max_results or settings.scheduler_max_results
    keywords = keywords or load_keywords(settings.keywords_file)

    summary = {
        "keywords": len(keywords),
        "search": {"results_saved": 0, "leads_created": 0},
        "crawl": {"tasks_processed": 0, "succeeded": 0, "failed": 0},
        "analysis": {"analyzed": 0},
    }

    # 1 + 2. Search
    service = SearchService(provider=search_provider or GoogleProvider())
    for kw in keywords:
        res = service.run_search(db, kw, country=country, max_results=max_results)
        summary["search"]["results_saved"] += res["results_saved"]
        summary["search"]["leads_created"] += res["leads_created"]
    db.commit()

    # 3. Crawl pending tasks
    crawl_report = process_pending(
        db, limit=max_results * len(keywords) + 50, crawler=website_crawler
    )
    summary["crawl"] = {
        "tasks_processed": crawl_report["tasks_processed"],
        "succeeded": crawl_report["succeeded"],
        "failed": crawl_report["failed"],
    }

    # 4 + 5. Analyse leads that were crawled but not yet scored.
    from app.models.lead import CompanyLead

    leads_to_analyze = (
        db.query(CompanyLead)
        .filter(CompanyLead.crawl_status == "success")
        .filter(CompanyLead.casting_need_score.is_(None))
        .all()
    )
    analyzed = 0
    for lead in leads_to_analyze:
        run_analysis(db, lead, crawled_text=lead.description or "")
        analyzed += 1
    summary["analysis"]["analyzed"] = analyzed

    return summary
