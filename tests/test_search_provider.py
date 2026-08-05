"""Phase 5 Stage 4: production search provider integration tests.

Covers SerpAPI response parsing, provider selection (SerpAPI vs Google
fallback), missing-API-key handling (clear ``SearchProviderError`` instead of
a silent empty list), empty-search-result handling, the ``GET /search/status``
endpoint, and the discovery job failing loudly with
``Search provider not configured``.
"""
import json

import pytest

from app.search import providers as providers_mod
from app.search.providers.base import SearchProviderError
from app.search.providers.google import GoogleProvider
from app.search.providers.serpapi import SERPAPI_ENDPOINT, SerpAPIProvider
from app.search.service import SearchService, default_provider


def _set_search_config(monkeypatch, *, provider="serpapi", key="secret-key"):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "search_provider", provider)
    monkeypatch.setattr(config_mod.settings, "serpapi_key", key)


def _fake_get(organic):
    """Build a fake httpx.get returning the given organic results."""

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"organic_results": organic}

    return lambda *a, **k: FakeResp()


# ---------------------------------------------------------------------------
# SerpAPI response parsing
# ---------------------------------------------------------------------------
def test_serpapi_response_parsing(monkeypatch):
    organic = [
        {
            "title": "Acme Castings GmbH",
            "link": "https://acme-castings.example.com",
            "snippet": "Precision aluminum die casting for the automotive industry.",
        },
        {"title": "No Link Co"},  # skipped: missing link
        {
            "title": "Beta Foundry",
            "link": "https://beta-foundry.example.com",
            "snippet": "Zinc die casting OEM.",
        },
    ]
    monkeypatch.setattr(providers_mod.serpapi.httpx, "get", _fake_get(organic))

    p = SerpAPIProvider(api_key="secret-key")
    results = p.search("aluminum die casting", country="de", max_results=10)
    assert len(results) == 2
    assert results[0].url == "https://acme-castings.example.com"
    assert results[0].title == "Acme Castings GmbH"
    assert results[0].snippet.startswith("Precision aluminum")
    assert results[0].rank == 1
    assert results[0].country == "de"
    assert results[0].keyword == "aluminum die casting"
    assert results[1].url == "https://beta-foundry.example.com"
    assert results[1].rank == 3  # rank mirrors the raw SERP position (item 3)


def test_serpapi_max_results_cap(monkeypatch):
    organic = [
        {"title": f"Co {i}", "link": f"https://co{i}.example.com"}
        for i in range(5)
    ]
    monkeypatch.setattr(providers_mod.serpapi.httpx, "get", _fake_get(organic))
    results = SerpAPIProvider(api_key="k").search("x", max_results=2)
    assert len(results) == 2


def test_serpapi_api_error_surfaces(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "Invalid API key"}

    monkeypatch.setattr(providers_mod.serpapi.httpx, "get", lambda *a, **k: FakeResp())
    with pytest.raises(SearchProviderError, match="SerpAPI error"):
        SerpAPIProvider(api_key="bad").search("x")


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
def test_provider_selection_serpapi(monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="secret-key")
    assert isinstance(default_provider(), SerpAPIProvider)
    assert isinstance(SearchService().provider, SerpAPIProvider)


def test_provider_selection_google_fallback(monkeypatch):
    _set_search_config(monkeypatch, provider="google", key="")
    assert isinstance(default_provider(), GoogleProvider)
    # unset SEARCH_PROVIDER also falls back to Google
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "search_provider", "")
    assert isinstance(default_provider(), GoogleProvider)


# ---------------------------------------------------------------------------
# Missing API key handling — loud failure, never a silent empty list
# ---------------------------------------------------------------------------
def test_serpapi_missing_key_raises(monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="")
    p = SerpAPIProvider(api_key="")
    with pytest.raises(SearchProviderError, match="Search provider not configured"):
        p.search("die casting")


def test_search_urls_raises_when_unconfigured(monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="")
    with pytest.raises(SearchProviderError, match="Search provider not configured"):
        SearchService().search_urls("die casting suppliers")


def test_empty_search_results_are_legit(monkeypatch):
    """A working provider returning no hits yields [] — not an error."""
    _set_search_config(monkeypatch, provider="serpapi", key="secret-key")
    monkeypatch.setattr(providers_mod.serpapi.httpx, "get", _fake_get([]))
    assert SearchService().search_urls("no such factory anywhere") == []


# ---------------------------------------------------------------------------
# GET /search/status
# ---------------------------------------------------------------------------
def test_search_status_serpapi_configured(client, monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="secret-key")
    r = client.get("/search/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "serpapi"
    assert body["configured"] is True
    assert body["serpapi_key_set"] is True
    assert "secret-key" not in json.dumps(body)


def test_search_status_serpapi_unconfigured(client, monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="")
    body = client.get("/search/status").json()
    assert body["provider"] == "serpapi"
    assert body["configured"] is False


def test_search_status_google_fallback(client, monkeypatch):
    _set_search_config(monkeypatch, provider="google", key="")
    body = client.get("/search/status").json()
    assert body["provider"] == "google"
    assert body["configured"] is True


# ---------------------------------------------------------------------------
# Discovery job fails loudly when the provider is unavailable
# ---------------------------------------------------------------------------
def test_discovery_job_fails_with_clear_error(client, monkeypatch):
    _set_search_config(monkeypatch, provider="serpapi", key="")
    created = client.post("/discovery/jobs", json={"keyword": "automotive die casting"})
    assert created.status_code == 201
    job_id = created.json()["job_id"]

    r = client.post(f"/discovery/jobs/{job_id}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "Search provider not configured"
    assert body["total"] == 0
