"""Google SERP provider.

Uses Playwright (headless Chromium) to run a Google search and a tolerant HTML
parser (``parse_google_html``) to extract organic results. The parser is kept
pure (operates on an HTML string) so it can be unit-tested without a browser.
"""
import re
from typing import List, Optional

from playwright.sync_api import sync_playwright

from app.config import settings
from app.search.base import BaseSearchProvider, SearchResult

# Google country -> hl (host language) mapping (subset; default falls back to en)
_COUNTRY_HL = {
    "us": "en",
    "uk": "en",
    "gb": "en",
    "ca": "en",
    "au": "en",
    "de": "de",
    "fr": "fr",
    "it": "it",
    "es": "es",
    "cn": "zh-CN",
    "jp": "ja",
    "in": "en",
    "mx": "es",
    "br": "pt",
}

# A "g" block is the classic organic-result container; we also accept "Gx5Zad".
_RESULT_BLOCK_RE = re.compile(r'class="(?:g|Gx5Zad|tF2Cxc)"', re.IGNORECASE)
_LINK_RE = re.compile(r'<a[^>]+href="(https?://[^"]+)"', re.IGNORECASE)
_TITLE_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_SNIPPET_RE = re.compile(
    r'class="(?:VwiC3b|MUxGbd|lyL57b|w8qArf|IZ6rdc)"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return _TAG_RE.sub(" ", html).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _strip_google_redirects(url: str) -> str:
    """Resolve Google /url?q= tracking links back to the real destination."""
    if url.startswith("https://www.google.com/url") or url.startswith(
        "https://google.com/url"
    ):
        m = re.search(r"[?&]q=(https?://[^&]+)", url)
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1))
    return url


def parse_google_html(html: str) -> List[SearchResult]:
    """Parse Google SERP HTML into a list of :class:`SearchResult`.

    Tolerant by design: it splits the page on known result-container markers,
    then extracts the first external link, the ``<h3>`` title and a snippet from
    each block. Designed to be testable with a representative HTML fixture.
    """
    results: List[SearchResult] = []
    blocks = _RESULT_BLOCK_RE.split(html)
    rank = 0
    for block in blocks[1:]:  # first split segment is pre-first-block preamble
        link_match = _LINK_RE.search(block)
        if not link_match:
            continue
        raw_url = link_match.group(1)
        url = _strip_google_redirects(raw_url)
        # Skip Google's own surfaces and static assets.
        if "google.com" in url or url.endswith((".css", ".js", ".png", ".jpg")):
            continue
        title_match = _TITLE_RE.search(block)
        snippet_match = _SNIPPET_RE.search(block)
        title = _clean(title_match.group(1)) if title_match else None
        snippet = _clean(snippet_match.group(1)) if snippet_match else None
        rank += 1
        results.append(
            SearchResult(
                keyword="",  # filled by the caller
                url=url,
                title=title,
                snippet=snippet,
                rank=rank,
            )
        )
    return results


class GoogleProvider(BaseSearchProvider):
    """Search Google via headless Chromium and parse the results."""

    def __init__(self, headless: Optional[bool] = None, timeout_ms: Optional[int] = None):
        self.headless = settings.crawler_headless if headless is None else headless
        self.timeout_ms = (
            settings.crawler_request_timeout if timeout_ms is None else timeout_ms
        )

    def search(
        self, keyword: str, country: str = "us", max_results: int = 20
    ) -> List[SearchResult]:
        hl = _COUNTRY_HL.get(country.lower(), "en")
        url = f"https://www.google.com/search?q={_quote(keyword)}&gl={country}&hl={hl}"
        html = self._fetch(url)
        results = parse_google_html(html)
        for r in results:
            r.keyword = keyword
            r.country = country
        return results[:max_results]

    def _fetch(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                page.goto(url, timeout=self.timeout_ms)
                # Scroll a little to trigger lazy-loaded results.
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(800)
                return page.content()
            finally:
                browser.close()


def _quote(s: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(s)
