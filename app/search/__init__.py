"""Google SERP search subpackage.

Provides:
- ``SearchResult`` dataclass & ``BaseSearchProvider`` interface
- ``GoogleProvider`` (Playwright-driven SERP scraping + HTML parsing)
- ``filters`` (directory/marketplace exclusion + manufacturer detection)
- ``keywords`` (default keyword library + loader)
- ``service`` (orchestrates search → filter → persist + create leads/tasks)
"""
from app.search.base import BaseSearchProvider, SearchResult
from app.search.filters import EXCLUDE_DOMAINS, filter_results, is_excluded
from app.search.google import GoogleProvider
from app.search.keywords import DEFAULT_KEYWORDS, load_keywords
from app.search.service import SearchService

__all__ = [
    "BaseSearchProvider",
    "SearchResult",
    "GoogleProvider",
    "EXCLUDE_DOMAINS",
    "filter_results",
    "is_excluded",
    "DEFAULT_KEYWORDS",
    "load_keywords",
    "SearchService",
]
