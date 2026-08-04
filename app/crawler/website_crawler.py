"""Website crawler (Phase 2.2 upgrade + Phase 3 Stage 2 intelligence).

``WebsiteCrawler`` crawls a company's key pages — homepage, about, products,
industries, solutions, contact, sitemap — and:

* checks ``robots.txt`` before fetching,
* discovers ``/sitemap.xml`` (and ``robots.txt`` ``Sitemap:`` directives),
* discovers internal links and classifies them (contact / product / company),
* extracts company-domain e-mails (see ``email_extractor``),
* extracts structured human contacts (name / title / email / linkedin),
* applies a per-page retry + timeout policy,
* reuses a browser context and an httpx session for speed,
* fetches pages concurrently (asyncio) with a token-bucket rate limiter.

The network layer is injectable (``fetcher``) so the orchestration logic is
fully testable without a browser. Two production fetchers are shipped:

* ``PlaywrightFetcher`` — drives headless Chromium (best for JS-heavy SPAs).
* ``HttpFetcher``      — lightweight ``httpx`` + ``bs4`` GET (fast for static sites).
"""
import asyncio
import threading
import time
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
from app.crawler.sitemap import discover_sitemap_urls


# ---------------------------------------------------------------------------
# Rate limiter (token bucket) — thread + asyncio safe via a lock.
# ---------------------------------------------------------------------------
class RateLimiter:
    """Simple token-bucket limiter: ``min(1, rate)`` requests per second.

    Use ``with limiter:`` (sync) or ``await limiter.acquire()`` (async) before a
    request. Defaults to ``rate=2`` (2 req/s); set ``rate=0`` to disable.
    """

    def __init__(self, rate: float = 2.0):
        self.rate = max(0.0, rate)
        self._lock = threading.Lock()
        self._tokens = rate
        self._last = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        if self.rate <= 0:
            self._tokens = 1
            return
        self._tokens = min(self.rate, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def __enter__(self) -> "RateLimiter":
        if self.rate <= 0:
            return self
        with self._lock:
            self._refill()
            while self._tokens < 1:
                time.sleep(0.01)
                self._refill()
            self._tokens -= 1
        return self

    def __exit__(self, *exc) -> None:
        return None

    async def acquire(self) -> None:
        """Async variant of the context-manager gate."""
        if self.rate <= 0:
            return
        loop = asyncio.get_event_loop()
        # Re-use the sync gate on a thread so we don't busy-spin the event loop.
        await loop.run_in_executor(None, self.__enter__)


# ---------------------------------------------------------------------------
# Lightweight HTTP fetcher (httpx + bs4) — fast for static / server-rendered
# sites. Reuses a single httpx.Client for connection pooling.
# ---------------------------------------------------------------------------
class HttpFetcher:
    """``url -> html`` fetcher backed by a pooled ``httpx.Client``."""

    def __init__(self, timeout: float = 15.0, rate: float = 2.0, headers: Optional[dict] = None):
        self._timeout = timeout
        self._limiter = RateLimiter(rate)
        self._headers = headers or {
            "User-Agent": "Mozilla/5.0 (diecasting-ai-lead-hunter)"
        }
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                timeout=self._timeout, headers=self._headers, follow_redirects=True
            )
        return self._client

    def __call__(self, url: str) -> str:
        with self._limiter:
            client = self._get_client()
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# ---------------------------------------------------------------------------
# Playwright fetcher with browser-context reuse (Phase 3 Stage 2).
# A single browser is launched once per crawler; every page is opened inside a
# reused ``browser_context`` so we don't pay the per-URL launch cost.
# ---------------------------------------------------------------------------
class BrowserContext:
    """Owns a Playwright browser + context and hands out pages cheaply."""

    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "BrowserContext":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        return self

    def fetch(self, url: str) -> str:
        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout_ms)
            page.wait_for_timeout(400)
            return page.content()
        finally:
            page.close()

    def __exit__(self, *exc) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()


def _playwright_fetcher(url: str, *, headless: bool, timeout_ms: int) -> str:
    """One-shot Playwright fetch (legacy path; kept for compatibility)."""
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
    """Structured crawl outcome matching the Phase 2.2 spec output.

    Canonical text field is ``text_content``. A ``text`` alias property is kept
    for backward compatibility so callers referencing either name work; new code
    should use ``text_content``.
    """

    url: str
    pages_found: List[str] = field(default_factory=list)
    text_content: str = ""
    emails: List[str] = field(default_factory=list)
    sitemap_urls: List[str] = field(default_factory=list)
    contacts: List[Dict] = field(default_factory=list)
    status: str = "success"
    pages_crawled: int = 0
    crawl_time: Optional[datetime] = None
    error: str = ""

    @property
    def text(self) -> str:
        """Alias for ``text_content`` (backward compatibility)."""
        return self.text_content

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "pages_found": self.pages_found,
            "text_content": self.text_content,
            "emails": self.emails,
            "sitemap_urls": self.sitemap_urls,
            "contacts": self.contacts,
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
        self._last_robots_text = ""

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
        robots_text = self._last_robots_text or ""

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
        # Initial contact extraction from the homepage.
        result.contacts = self._extract_contacts(home_html, domain)

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

        # 4b. Sitemap discovery (robots Sitemap: + /sitemap.xml).
        try:
            result.sitemap_urls = discover_sitemap_urls(
                homepage, robots_text=robots_text, fetcher=self._fetch_text
            )
        except Exception:
            result.sitemap_urls = []

        if any("/sitemap.xml" in u for u in work):
            result.pages_found.append(next(u for u in work if "/sitemap.xml" in u))
        # Add a handful of sitemap URLs to the work-list so their pages also get
        # crawled (bounded so we never explode the crawl).
        for sm in result.sitemap_urls[: min(len(result.sitemap_urls), self.max_pages)]:
            if sm not in work:
                work.append(sm)

        # 5. Visit each candidate (skip homepage, already fetched) concurrently.
        pending = [
            url
            for url in work
            if url.rstrip("/") != homepage.rstrip("/")
            and is_path_allowed(robots_rules, urlparse(url).path or "/")
        ]
        fetched = self._crawl_concurrent(pending, limit=self.max_pages - 1)
        for url, html in fetched:
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
            # Merge contacts found on this page (de-duplicated later).
            result.contacts.extend(self._extract_contacts(html, domain))

        result.pages_crawled = pages_crawled
        result.text_content = result.text_content.strip()[:8000]
        result.emails = extract_and_filter(result.text_content, site_domain=domain)
        # de-duplicate pages_found and contacts preserving order
        seen = set()
        result.pages_found = [u for u in result.pages_found if not (u in seen or seen.add(u))]
        result.contacts = self._dedup_contacts(result.contacts)
        result.status = "success"
        result.crawl_time = datetime.now(timezone.utc)
        return result

    # ------------------------------------------------------------------ #
    # concurrency + helpers
    # ------------------------------------------------------------------ #
    def _crawl_concurrent(self, urls: List[str], limit: int) -> List[tuple]:
        """Fetch ``urls`` concurrently (rate-limited) and return ``(url, html)``.

        Stops after ``limit`` successful pages. Failures are skipped (a missing
        subpage must not fail the whole crawl). Runs an event loop internally so
        the public ``crawl()`` stays synchronous and compatible with the API.
        """
        if not urls:
            return []

        async def _worker(sem, url, out):
            async with sem:
                try:
                    loop = asyncio.get_event_loop()
                    html = await loop.run_in_executor(None, self._fetch_with_retry, url)
                    out.append((url, html))
                except Exception:
                    return

        async def _run():
            sem = asyncio.Semaphore(max(1, min(8, self.max_pages)))
            collected = []
            tasks = [asyncio.ensure_future(_worker(sem, u, collected)) for u in urls]
            # Consume tasks as they complete; stop early once we hit ``limit``.
            for coro in asyncio.as_completed(tasks):
                await coro
                if len(collected) >= limit:
                    for t in tasks:
                        t.cancel()
                    break
            return collected

        return asyncio.run(_run())

    def _extract_contacts(self, html: str, domain: str) -> List[Dict]:
        """Best-effort contact extraction; returns [] on any error."""
        try:
            from app.crawler.contact_extractor import extract_contacts as _ec

            return _ec(html, site_domain=domain)
        except Exception:
            return []

    @staticmethod
    def _dedup_contacts(contacts: List[Dict]) -> List[Dict]:
        out = []
        keys = set()
        for c in contacts:
            key = (c.get("name"), c.get("email"))
            if key in keys:
                continue
            keys.add(key)
            out.append(c)
        return out

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _load_robots(self, homepage: str) -> Dict[str, List[str]]:
        base = homepage.rstrip("/")
        robots_url = urljoin(base + "/", "robots.txt")
        try:
            text = self.fetcher(robots_url)
            self._last_robots_text = text or ""
            return parse_robots(text)
        except Exception:
            self._last_robots_text = ""
            return {"*": []}

    def _fetch_text(self, url: str) -> str:
        """Raw-text fetcher used by sitemap discovery; returns "" on failure.

        Unlike ``_fetch_with_retry`` this does NOT raise, because a missing
        sitemap must not abort discovery.
        """
        try:
            data = self.fetcher(url)
            return data if isinstance(data, str) else ""
        except Exception:
            return ""


def crawl_website(homepage: str, **kwargs) -> dict:
    """Convenience helper returning a ``WebsiteCrawler`` result as a dict."""
    return WebsiteCrawler(**kwargs).crawl(homepage).to_dict()
