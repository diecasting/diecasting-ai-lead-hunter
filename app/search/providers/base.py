"""Search provider abstraction and the ``SearchResult`` data class."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchResult:
    """A single organic search hit."""

    keyword: str
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    country: Optional[str] = None
    rank: int = 0


class SearchProviderError(RuntimeError):
    """Raised when the configured search provider cannot run.

    Used e.g. when ``SEARCH_PROVIDER=serpapi`` is set without a ``SERPAPI_KEY``
    — the discovery queue surfaces this as a clear job error instead of
    silently returning zero URLs.
    """


class BaseSearchProvider(ABC):
    """Interface implemented by concrete SERP providers (Google, SerpAPI, ...)."""

    @abstractmethod
    def search(
        self, keyword: str, country: str = "us", max_results: int = 20
    ) -> List[SearchResult]:
        """Return a list of :class:`SearchResult` for the given keyword."""
        raise NotImplementedError
