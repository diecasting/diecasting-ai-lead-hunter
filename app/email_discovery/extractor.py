"""Website e-mail crawler (Phase 8).

Crawls a company's homepage plus a handful of high-value pages (contact / about
/ team) and extracts on-domain corporate e-mails. The network layer is fully
injectable (``fetcher``) so the extraction logic is unit-testable without a
browser or the network.

For production the default fetcher uses a lightweight ``httpx`` GET; the heavier
``WebsiteCrawler`` (Playwright / httpx, sitemap + robots + concurrency) from
``app.crawler`` can be swapped in if a deeper crawl is required.
"""
from typing import Callable, List, Optional, Set
from urllib.parse import urljoin, urlparse

from app.crawler.email_extractor import extract_and_filter

# Relative paths (relative to the homepage) worth scanning for contact e-mails.
_CONTACT_PATHS = [
    "",
    "contact",
    "contact-us",
    "about",
    "about-us",
    "company",
    "team",
    "support",
    "enquiry",
    "enquiry",
]


def _normalize_homepage(homepage: str) -> str:
    homepage = (homepage or "").strip()
    if not homepage:
        return ""
    if not (homepage.startswith("http://") or homepage.startswith("https://")):
        homepage = "https://" + homepage
    return homepage.rstrip("/")


def site_domain(homepage: str) -> str:
    """Return the lower-cased registrable host for ``homepage`` (best effort)."""
    host = urlparse(homepage).hostname or ""
    return host.lower()


class WebsiteEmailCrawler:
    """Lightweight crawler that collects e-mails from a company website."""

    def __init__(
        self,
        homepage: str,
        *,
        fetcher: Optional[Callable[[str], str]] = None,
        max_pages: int = 8,
    ) -> None:
        self.homepage = _normalize_homepage(homepage)
        self._fetcher = fetcher
        self.max_pages = max(1, min(50, max_pages))

    @property
    def domain(self) -> str:
        return site_domain(self.homepage)

    def _fetch(self, url: str) -> str:
        if self._fetcher is not None:
            try:
                return self._fetcher(url) or ""
            except Exception:
                return ""
        # Default production fetcher (no browser): a single httpx GET.
        try:
            import httpx
        except Exception:  # pragma: no cover - httpx always installed
            return ""
        try:
            resp = httpx.get(
                url,
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (diecasting-ai-lead-hunter)"},
            )
            return resp.text or ""
        except Exception:
            return ""

    def crawl(self) -> List[str]:
        """Return a prioritised, de-duplicated list of on-domain e-mails."""
        if not self.homepage:
            return []
        domain = self.domain
        collected: Set[str] = set()
        pages: List[str] = []
        for p in _CONTACT_PATHS:
            url = self.homepage if p == "" else urljoin(self.homepage + "/", p)
            if url not in pages:
                pages.append(url)
        for url in pages[: self.max_pages]:
            html = self._fetch(url)
            if not html:
                continue
            collected.update(extract_and_filter(html, site_domain=domain))
        # Re-prioritise across the whole set so on-domain addresses come first.
        return extract_and_filter(" ".join(sorted(collected)), site_domain=domain)
