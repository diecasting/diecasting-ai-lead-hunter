"""Search providers package (Phase 5 Stage 4).

* ``base``    — :class:`BaseSearchProvider` interface, :class:`SearchResult`,
                :class:`SearchProviderError`.
* ``google``  — :class:`GoogleProvider`: existing Playwright SERP scraping
                (kept as the default / fallback provider).
* ``serpapi`` — :class:`SerpAPIProvider`: production search via the SerpAPI
                JSON API (``SEARCH_PROVIDER=serpapi`` + ``SERPAPI_KEY``).

:func:`app.search.service.SearchService` picks the provider: SerpAPI when
configured, otherwise the Google fallback.
"""
from app.search.providers.base import (
    BaseSearchProvider,
    SearchProviderError,
    SearchResult,
)
from app.search.providers.google import GoogleProvider, parse_google_html
from app.search.providers.serpapi import SERPAPI_ENDPOINT, SerpAPIProvider

__all__ = [
    "BaseSearchProvider",
    "SearchProviderError",
    "SearchResult",
    "GoogleProvider",
    "parse_google_html",
    "SerpAPIProvider",
    "SERPAPI_ENDPOINT",
]
