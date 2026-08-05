"""Search subpackage.

Provides:
- ``SearchResult`` dataclass & ``BaseSearchProvider`` interface + the
  ``SearchProviderError`` raised when a provider cannot run
- ``providers`` — ``GoogleProvider`` (Playwright SERP scraping fallback) and
  ``SerpAPIProvider`` (production API; ``SEARCH_PROVIDER=serpapi`` +
  ``SERPAPI_KEY``)
- ``filters`` (directory/marketplace exclusion + manufacturer detection)
- ``keywords`` (default keyword library + loader)
- ``service`` (orchestrates search → filter → persist + create leads/tasks)
"""
from app.search.filters import EXCLUDE_DOMAINS, filter_results, is_excluded
from app.search.keywords import DEFAULT_KEYWORDS, load_keywords
from app.search.providers import (
    BaseSearchProvider,
    GoogleProvider,
    SearchProviderError,
    SearchResult,
    SerpAPIProvider,
)
from app.search.service import SearchService

__all__ = [
    "BaseSearchProvider",
    "SearchProviderError",
    "SearchResult",
    "GoogleProvider",
    "SerpAPIProvider",
    "EXCLUDE_DOMAINS",
    "filter_results",
    "is_excluded",
    "DEFAULT_KEYWORDS",
    "load_keywords",
    "SearchService",
]
