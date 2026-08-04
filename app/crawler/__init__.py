"""Web crawler package (Playwright-based website crawler, Phase 2.2)."""
from app.crawler.email_extractor import extract_and_filter, extract_emails, filter_emails
from app.crawler.page_discovery import (
    classify_path,
    candidate_urls,
    discover_pages,
    extract_links,
    extract_text,
)
from app.crawler.website_crawler import (
    CrawlResult,
    WebsiteCrawler,
    crawl_website,
    is_path_allowed,
    parse_robots,
)

__all__ = [
    "WebsiteCrawler",
    "CrawlResult",
    "crawl_website",
    "parse_robots",
    "is_path_allowed",
    "page_discovery",
    "email_extractor",
    "extract_emails",
    "filter_emails",
    "extract_and_filter",
    "classify_path",
    "candidate_urls",
    "discover_pages",
    "extract_links",
    "extract_text",
]
