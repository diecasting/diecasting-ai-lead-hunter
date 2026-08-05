"""SerpAPI provider — production search via the SerpAPI JSON API.

Configured with ``SEARCH_PROVIDER=serpapi`` and ``SERPAPI_KEY``. Uses the
Google engine on SerpAPI (``https://serpapi.com/search.json?engine=google``)
— a maintained API that avoids the anti-bot / browser / network problems of
HTML scraping. Each organic result is mapped to a :class:`SearchResult`.
"""
from typing import List, Optional

import httpx

from app.config import settings
from app.search.providers.base import BaseSearchProvider, SearchResult, SearchProviderError

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 30


class SerpAPIProvider(BaseSearchProvider):
    """Search Google via SerpAPI's JSON endpoint."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = REQUEST_TIMEOUT):
        self.api_key = (api_key or settings.serpapi_key or "").strip()
        self.timeout = timeout

    def search(
        self, keyword: str, country: str = "us", max_results: int = 20
    ) -> List[SearchResult]:
        """Return organic results for ``keyword`` (title / url / snippet).

        Raises :class:`SearchProviderError` when the API key is missing so the
        discovery queue fails loudly instead of silently yielding zero URLs.
        """
        if not self.api_key:
            raise SearchProviderError("Search provider not configured")

        params = {
            "engine": "google",
            "q": keyword,
            "api_key": self.api_key,
            "num": min(int(max_results or 20), 100),
        }
        if country:
            params["gl"] = country

        resp = httpx.get(SERPAPI_ENDPOINT, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise SearchProviderError(f"SerpAPI error: {data['error']}")

        organic = (
            (data.get("organic_results") or [])
            if isinstance(data, dict)
            else []
        )
        results: List[SearchResult] = []
        for i, item in enumerate(organic, start=1):
            link = (item.get("link") or "").strip()
            if not link:
                continue
            results.append(
                SearchResult(
                    keyword=keyword,
                    url=link,
                    title=item.get("title"),
                    snippet=item.get("snippet"),
                    country=country,
                    rank=i,
                )
            )
        return results[: max_results]
