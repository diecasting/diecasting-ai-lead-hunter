"""Result filtering for the SERP search pipeline.

Two responsibilities:
1. **Hard exclusion** of directory / marketplace / aggregator / encyclopaedia
   domains that are useless as direct B2B leads (Alibaba, Made-in-China,
   IndiaMart, Thomasnet, Wikipedia, ...).
2. **Manufacturer detection** — a lightweight heuristic that flags results that
   read like a real manufacturer / OEM / factory / engineering company, which is
   what we actually want to keep.
"""
from typing import List
from urllib.parse import urlparse

from app.search.base import SearchResult

# --- Hard-exclude domains (substring match on the registered domain) ---------
EXCLUDE_DOMAINS = {
    "alibaba.com",
    "made-in-china.com",
    "indiamart.com",
    "thomasnet.com",
    "tradeindia.com",
    "globalsources.com",
    "ec21.com",
    "dhgate.com",
    "export.com",
    "kompass.com",
    "europages.com",
    "hotfrog.com",
    "yellowpages.com",
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "pinterest.com",
    "reddit.com",
    "amazon.com",
    "ebay.com",
    "twitter.com",
    "x.com",
    "gov",
    "edu",
}

# Signals that indicate a real manufacturer / OEM / factory / engineering co.
KEEP_SIGNALS = (
    "manufacturer",
    "manufacturing",
    "oem",
    "odm",
    "factory",
    "factories",
    "engineering company",
    "engineering",
    "die casting",
    "die-casting",
    "precision machining",
    "foundry",
    "cnc machining",
)

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "mail.com",
    "live.com",
    "msn.com",
}


def _registered_domain(url: str) -> str:
    """Return the lower-cased host (or TLD-ish tail) for a URL."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    return host


def is_excluded(url: str, title: str = "", snippet: str = "") -> bool:
    """True if the result belongs to a directory / marketplace / aggregator."""
    host = _registered_domain(url)
    if not host:
        return False
    # Drop obvious non-company TLDs (e.g. .gov, .edu) and known platforms.
    if host.endswith(".gov") or host.endswith(".edu"):
        return True
    for bad in EXCLUDE_DOMAINS:
        if host == bad or host.endswith("." + bad) or bad in host:
            return True
    return False


def detect_manufacturer(title: str = "", snippet: str = "", text: str = "") -> bool:
    """Heuristic: does this result look like a manufacturer / OEM / factory?"""
    haystack = f"{title} {snippet} {text}".lower()
    return any(sig in haystack for sig in KEEP_SIGNALS)


def filter_results(
    results: List[SearchResult],
    exclude_directories: bool = True,
    keep_only_manufacturers: bool = False,
) -> List[SearchResult]:
    """Apply the configured filters to a list of search results.

    ``exclude_directories`` removes marketplace / directory / aggregator hits.
    ``keep_only_manufacturers`` additionally drops anything that does not match
    the manufacturer heuristic (use with care — it is stricter).
    """
    out: List[SearchResult] = []
    for r in results:
        if exclude_directories and is_excluded(r.url, r.title or "", r.snippet or ""):
            continue
        if keep_only_manufacturers and not detect_manufacturer(
            r.title or "", r.snippet or ""
        ):
            continue
        out.append(r)
    return out
