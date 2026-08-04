"""Page-discovery helpers for the website crawler (Phase 2.2).

This module turns raw HTML into a structured map of the pages a sales-intent
crawler cares about:

* Contact pages  -> ``/contact``, ``/contact-us``, ``/contactus``,
  ``/sales``, ``/inquiry``, ``/quote``, ``/rfq``
* Product pages  -> ``/products``, ``/product``, ``/solution``,
  ``/capabilities``, ``/manufacturing``
* Company pages  -> ``/about``, ``/company``, ``/factory``

It also exposes the pure, browser-free functions (link / text / title
extraction, path classification) that the unit tests exercise directly.
"""
import re
from typing import Dict, List
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Page taxonomy
# ---------------------------------------------------------------------------
PAGE_TYPES = ["homepage", "about", "products", "industries", "solutions", "contact", "sitemap"]

# Canonical candidate paths the crawler will *proactively* try to visit
# (mirrors the Phase 2.2 spec: homepage + about/company + products/industries/
# solutions + the various contact/quote entry points + sitemap).
CANONICAL_PATHS: List[str] = [
    "/",
    "/about",
    "/about-us",
    "/company",
    "/products",
    "/industries",
    "/solutions",
    "/contact",
    "/contact-us",
    "/request-quote",
    "/rfq",
    "/sitemap.xml",
]

# Tokens used to *classify* links discovered while crawling (section 2 of spec).
_CONTACT_TOKENS = ["contact", "contactus", "sales", "inquiry", "inquiries", "quote", "rfq"]
_PRODUCT_TOKENS = ["product", "products", "solution", "solutions", "capabilit", "manufacturing"]
_COMPANY_TOKENS = ["about", "company", "factory", "our-company", "who-we-are"]

# Canonical path segments mapped directly to a page type (fast, exact match).
_PATH_TYPE = {
    "/contact": "contact",
    "/contact-us": "contact",
    "/contactus": "contact",
    "/sales": "contact",
    "/inquiry": "contact",
    "/inquiries": "contact",
    "/request-quote": "contact",
    "/request_a_quote": "contact",
    "/get-a-quote": "contact",
    "/quote": "contact",
    "/rfq": "contact",
    "/products": "product",
    "/product": "product",
    "/solutions": "product",
    "/solution": "product",
    "/capabilities": "product",
    "/manufacturing": "product",
    "/about": "company",
    "/about-us": "company",
    "/company": "company",
    "/our-company": "company",
    "/who-we-are": "company",
    "/factory": "company",
}

_HREF_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SKIP_TAGS = re.compile(
    r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def classify_path(path: str) -> str:
    """Classify a URL path into ``contact`` / ``product`` / ``company`` / ``other``."""
    norm = (path or "/").split("?")[0].rstrip("/").lower()
    if norm == "":
        norm = "/"
    if norm in _PATH_TYPE:
        return _PATH_TYPE[norm]
    # Token heuristics for paths not in the exact map.
    if any(tok in norm for tok in _CONTACT_TOKENS):
        return "contact"
    if any(tok in norm for tok in _PRODUCT_TOKENS):
        return "product"
    if any(tok in norm for tok in _COMPANY_TOKENS):
        return "company"
    return "other"


def candidate_urls(homepage: str) -> Dict[str, str]:
    """Return ``{normalized_path: absolute_url}`` for every canonical path.

    Each distinct path is visited once (de-duplicated) and the homepage (``/``)
    is kept so callers can skip it explicitly.
    """
    base = homepage.rstrip("/")
    out: Dict[str, str] = {}
    for p in CANONICAL_PATHS:
        np = p.rstrip("/") or "/"
        if np in out:
            continue
        if p == "/":
            out[np] = base + "/"
        else:
            out[np] = urljoin(base + "/", p.lstrip("/"))
    return out


def extract_links(html: str, base_domain: str = "") -> List[str]:
    """Extract internal (or all http) absolute links from HTML."""
    links: List[str] = []
    for m in _HREF_RE.finditer(html or ""):
        href = m.group(1).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(("https://" + base_domain), href) if base_domain else href
        links.append(href)
    if base_domain:
        links = [l for l in links if base_domain in (urlparse(l).netloc or "")]
    seen = set()
    out = []
    for l in links:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


def discover_pages(home_url: str, html: str) -> Dict[str, List[str]]:
    """Scan a page's HTML and return discovered pages grouped by type.

    Returns ``{"contact": [...], "product": [...], "company": [...]}`` — the
    ``discovered_pages`` structure requested in the spec. Only same-domain links
    are considered so we never wander off to third-party sites.
    """
    domain = (urlparse(home_url).hostname or "").lower()
    discovered: Dict[str, List[str]] = {"contact": [], "product": [], "company": []}
    seen: Dict[str, set] = {"contact": set(), "product": set(), "company": set()}
    for link in extract_links(html or "", base_domain=domain):
        ptype = classify_path(urlparse(link).path)
        if ptype in discovered and link not in seen[ptype]:
            seen[ptype].add(link)
            discovered[ptype].append(link)
    return discovered


def extract_text(html: str, max_chars: int = 4000) -> str:
    """Strip tags/scripts and return a compact readable text sample."""
    if not html:
        return ""
    cleaned = _SKIP_TAGS.sub(" ", html)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned[:max_chars]


def extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    if m:
        return _TAG_RE.sub("", m.group(1)).strip()
    return ""
