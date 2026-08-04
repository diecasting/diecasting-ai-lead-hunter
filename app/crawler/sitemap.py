"""Sitemap discovery (Phase 3 Stage 2).

Discovers a company's sitemap(s) from two sources and parses them into a flat
list of URLs:

1. ``robots.txt`` ``Sitemap:`` directives (multiple allowed).
2. The canonical ``/sitemap.xml`` fallback.

Both ``<urlset>`` (per-page ``<loc>``) and ``<sitemapindex>`` (nested
``<loc>`` to child sitemaps) formats are handled. All network I/O goes through
the injected ``fetcher`` so the logic is fully testable without a browser.
"""
import re
from typing import Callable, List, Optional
from urllib.parse import urljoin, urlparse

# A sitemap URL must reference the same registered host (no off-site crawling).
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)


def discover_sitemap_urls(
    homepage: str,
    robots_text: str = "",
    fetcher: Optional[Callable[[str], str]] = None,
    seen: Optional[set] = None,
) -> List[str]:
    """Return de-duplicated absolute URLs found in the site's sitemap(s).

    Args:
        homepage: site root used to resolve relative sitemap paths.
        robots_text: raw robots.txt text (may contain ``Sitemap:`` lines).
        fetcher: ``url -> raw xml text``. When ``None`` we only use explicitly
            provided sitemap URLs and cannot fetch/parse them (returns ``[]``).
        seen: internal recursion guard for sitemap indexes.

    The function is safe: any fetch / parse error is swallowed and the URL is
    simply skipped (a missing sitemap must not crash the crawl).
    """
    base = homepage.rstrip("/")
    sitemap_sources: List[str] = []

    # 1. robots.txt Sitemap: directives
    for line in (robots_text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.lower().startswith("sitemap:"):
            loc = line.split(":", 1)[1].strip()
            if loc:
                sitemap_sources.append(loc if loc.startswith("http") else urljoin(base + "/", loc.lstrip("/")))

    # 2. canonical fallback
    sitemap_sources.append(urljoin(base + "/", "sitemap.xml"))

    if seen is None:
        seen = set()
    results: List[str] = []

    for sm_url in sitemap_sources:
        if not sm_url or sm_url in seen:
            continue
        seen.add(sm_url)
        if fetcher is None:
            continue
        try:
            xml = fetcher(sm_url)
        except Exception:
            continue
        # A sitemap index lists child sitemaps; fetch + parse each child too.
        child_urls = _parse_sitemap_index(xml)
        if child_urls:
            for child in child_urls:
                if child in seen:
                    continue
                seen.add(child)
                try:
                    child_xml = fetcher(child)
                except Exception:
                    continue
                for loc in _parse_urlset(child_xml):
                    if loc not in results:
                        results.append(loc)
        else:
            for loc in _parse_urlset(xml):
                if loc not in results:
                    results.append(loc)

    return results


def _parse_sitemap_index(xml: str) -> List[str]:
    """Extract child sitemap ``<loc>`` entries from a sitemap index document."""
    if "<sitemapindex" not in (xml or "").lower():
        return []
    return [m.group(1).strip() for m in _LOC_RE.finditer(xml)]


def _parse_urlset(xml: str) -> List[str]:
    """Extract page ``<loc>`` entries from a urlset document."""
    if "<urlset" not in (xml or "").lower():
        return []
    out = []
    for m in _LOC_RE.finditer(xml or ""):
        loc = m.group(1).strip()
        if loc and loc not in out:
            out.append(loc)
    return out
