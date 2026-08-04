"""Playwright-based website crawler (Phase 2.2 upgrade).

``WebsiteCrawler`` crawls a company's key pages — homepage, about, products,
industries, solutions, contact and sitemap — and:

* checks ``robots.txt`` before fetching,
* discovers ``/sitemap.xml``,
* discovers internal links and classifies them (contact / product / company),
* extracts company-domain e-mails (see ``email_extractor``),
* applies a per-page retry + timeout policy.

The network layer is injectable (``fetcher``) so the orchestration logic is
fully testable without a browser. The default fetcher drives headless Chromium
via Playwright.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from app.config import settings
from app.crawler.email_extractor import extract_and_filter
from app.crawler.page_discovery import (
    candidate_urls,
    discover_pages,
    extract_text,
    extract_title,
)


def _playwright_fetcher(url: str, *, headless: bool, timeout_ms: int) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(url, timeout=timeout_ms)
            page.wait_for_timeout(400)
            return page.content()
        finally:
            browser.close()


def parse_robots(robots_text: str, user_agent: str = "*") -> Dict[str, List[str]]:
    """Minimal robots.txt parser -> ``{user_agent: [disallowed_paths]}``."""
    rules: Dict[str, List[str]] = {"*": []}
    current = "*"
    for raw in (robots_text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            current = val.lower() or "*"
            rules.setdefault(current, [])
        elif key == "disallow":
            if val:
                rules.setdefault(current, []).append(val)
    # Merge the catch-all "*" rules into any specific agent we're acting as.
    if user_agent != "*" and user_agent in rules:
        return {"*": rules["*"] + rules[user_agent]}
    return rules


def is_path_allowed(rules: Dict[str, List[str]], path: str) -> bool:
    """Return True if ``path`` is allowed by the (already-merged) rules."""
    for disallow in rules.get("*", []):
        if disallow == "/":
            return False
        if disallow and path.startswith(disallow):
            return False
    return True


@dataclass
class CrawlResult:
    """Structured crawl outcome matching the Phase 2.2 spec output."""

    url: str
    pages_found: List[str] = field(default_factory=list)
    text_content: str = ""
    emails: List[str] = field(default_factory=list)
    status: str = "success"
    pages_crawled: int = 0
    crawl_time: Optional[datetime] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "pages_found": self.pages_found,
            "text_content": self.text_content,
            "emails": self.emails,
            "status": self.status,
            "pages_crawled": self.pages_crawled,
            "crawl_time": self.crawl_time.isoformat() if self.crawl_time else None,
            "error": self.error,
        }


class WebsiteCrawler:
    """Crawl a single company website and extract sales-intent signals."""

    def __init__(
        self,
        headless: Optional[bool] = None,
        max_pages: Optional[int] = None,
        max_retries: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        fetcher: Optional[Callable[[str], str]] = None,
    ):
        self.headless = settings.crawler_headless if headless is None else headless
        self.max_pages = settings.crawler_max_pages if max_pages is None else max_pages
        self.max_retries = (
            settings.crawler_max_retries if max_retries is None else max_retries
        )
        self.timeout_ms = (
            settings.crawler_request_timeout if timeout_ms is None else timeout_ms
        )
        self._fetcher = fetcher

    @property
    def fetcher(self) -> Callable[[str], str]:
        if self._fetcher is not None:
            return self._fetcher
        return lambda u: _playwright_fetcher(
            u, headless=self.headless, timeout_ms=self.timeout_ms
        )

    # ------------------------------------------------------------------ #
    # fetch + retry
    # ------------------------------------------------------------------ #
    def _fetch_with_retry(self, url: str) -> str:
        last_err = ""
        for _ in range(1, self.max_retries + 1):
            try:
                return self.fetcher(url)
            except Exception as exc:  # network / timeout / parse
                last_err = f"{type(exc).__name__}: {exc}"
                continue
        raise RuntimeError(f"failed after {self.max_retries} attempts: {last_err}")

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def crawl(self, homepage: str) -> CrawlResult:
        homepage = (homepage or "").strip()
        domain = (urlparse(homepage).hostname or "").lower()
        result = CrawlResult(url=homepage)

        # 1. robots.txt check (best effort — ignore if unreachable).
        robots_rules = self._load_robots(homepage)

        # 2. Build candidate pages from the canonical path set.
        candidates: Dict[str, str] = candidate_urls(homepage)

        # 3. Fetch the homepage (counted as the first crawled page).
        try:
            home_html = self._fetch_with_retry(homepage)
        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            result.crawl_time = datetime.now(timezone.utc)
            return result

        result.text_content = extract_text(home_html)
        pages_crawled = 1

        # 4. Build the ordered work-list: canonical candidates first, then any
        #    additional internal links discovered on the homepage.
        work: List[str] = []
        seen_paths: set = set()
        for _path, url in candidate_urls(homepage).items():
            np = urlparse(url).path.rstrip("/") or "/"
            if np in seen_paths:
                continue
            seen_paths.add(np)
            work.append(url)

        for ptype, urls in discover_pages(homepage, home_html).items():
            for u in urls:
                np = urlparse(u).path.rstrip("/") or "/"
                if np not in seen_paths:
                    seen_paths.add(np)
                    work.append(u)

        if any("/sitemap.xml" in u for u in work):
            result.pages_found.append(next(u for u in work if "/sitemap.xml" in u))

        # 5. Visit each candidate (skip homepage, already fetched) with retry.
        for url in work:
            if url.rstrip("/") == homepage.rstrip("/"):
                continue
            if pages_crawled >= self.max_pages:
                break
            path = urlparse(url).path or "/"
            if not is_path_allowed(robots_rules, path):
                continue
            try:
                html = self._fetch_with_retry(url)
                pages_crawled += 1
                result.pages_found.append(url)
                result.text_content += " " + extract_text(html)
                # Extend the work-list with newly discovered internal links.
                for ptype, urls in discover_pages(url, html).items():
                    for u in urls:
                        np = urlparse(u).path.rstrip("/") or "/"
                        if np not in seen_paths:
                            seen_paths.add(np)
                            work.append(u)
            except Exception:
                # A missing subpage must not fail the whole crawl.
                continue

        result.pages_crawled = pages_crawled
        result.text_content = result.text_content.strip()[:8000]
        result.emails = extract_and_filter(result.text_content, site_domain=domain)
        # de-duplicate pages_found preserving order
        seen = set()
        result.pages_found = [u for u in result.pages_found if not (u in seen or seen.add(u))]
        result.status = "success"
        result.crawl_time = datetime.now(timezone.utc)
        return result

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _load_robots(self, homepage: str) -> Dict[str, List[str]]:
        base = homepage.rstrip("/")
        robots_url = urljoin(base + "/", "robots.txt")
        try:
            text = self.fetcher(robots_url)
            return parse_robots(text)
        except Exception:
            return {"*": []}


def crawl_website(homepage: str, **kwargs) -> dict:
    """Convenience helper returning a ``WebsiteCrawler`` result as a dict."""
    return WebsiteCrawler(**kwargs).crawl(homepage).to_dict()
