"""Playwright-based crawler that discovers die-casting company leads.

This is a Phase-1 reference implementation: it runs a search query, follows the
result links, and extracts lightweight company signals (name, website, domain,
and any e-mail found in the result snippet). It is intentionally simple and
robust — production crawlers should add politeness/rate-limiting, robots.txt
respect, and per-source parsers.
"""
import re
from dataclasses import asdict, dataclass
from typing import List, Optional

from playwright.sync_api import sync_playwright

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
DOMAIN_RE = re.compile(r"https?://([^/]+)/?")


@dataclass
class CrawledCompany:
    name: str
    website: Optional[str] = None
    domain: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    employee_count: Optional[int] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    source: str = "crawler"


class DieCastingCrawler:
    def __init__(self, headless: bool = True, max_pages: int = 50):
        self.headless = headless
        self.max_pages = max_pages

    def search(
        self, query: str = "aluminum die casting manufacturer", max_results: int = 10
    ) -> List[CrawledCompany]:
        results: List[CrawledCompany] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                page.goto("https://duckduckgo.com/html/", timeout=30000)
                page.fill("input[name=q]", query)
                page.press("input[name=q]", "Enter")
                page.wait_for_selector("a.result__a", timeout=15000)
                links = page.query_selector_all("a.result__a")[:max_results]
                for link in links:
                    title = (link.inner_text() or "").strip()
                    href = link.get_attribute("href")
                    if not href or not title:
                        continue
                    company = CrawledCompany(
                        name=title,
                        website=href,
                        domain=self._domain(href),
                        industry="Die casting",
                    )
                    snippet = link.evaluate(
                        "el => (el.closest('.result') "
                        "?.querySelector('.result__snippet')?.innerText) || ''"
                    )
                    match = EMAIL_RE.search(snippet or "")
                    if match:
                        company.contact_email = match.group(0)
                        company.description = (snippet or "").strip() or None
                    results.append(company)
            finally:
                browser.close()
        return results

    @staticmethod
    def _domain(url: str) -> Optional[str]:
        match = DOMAIN_RE.match(url)
        return match.group(1) if match else None


def crawl(
    query: str = "aluminum die casting manufacturer", max_results: int = 10
) -> List[dict]:
    """Convenience helper returning crawled companies as plain dicts."""
    crawler = DieCastingCrawler()
    return [asdict(c) for c in crawler.search(query=query, max_results=max_results)]
