"""Phase 5 Stage 1 — AI Lead Discovery Engine tests.

Covers:
  * website extraction      — profile fields populated from crawled text
  * signal detection        — materials / processes / industries / buying
                              signals / supplier opportunities
  * score calculation       — deterministic lead score + confidence bounds
  * API                     — analyze-url validation + persistence,
                              graceful crawl-failure, add-to-CRM (dedup + 409)
"""
from fastapi.testclient import TestClient

from app.crawler.website_crawler import CrawlResult
from app.discovery import crud as discovery_crud
from app.discovery.analyzer import (
    DiscoveryResult,
    analyze_website,
    compute_lead_score,
    derive_company_name,
)

SAMPLE_HTML = """
Acme Castings GmbH is a contract manufacturer of precision aluminum and
ADC12 die-cast components for the automotive and aerospace industries.
We specialize in high pressure die casting, gravity casting, cnc machining
and in-house tooling. We are looking for suppliers for a new EV motor
housing program and currently sourcing die-cast housings; request for
quotation (RFQ) is open. Production capability: custom parts, made to order,
volumes from prototype to 500k/year. Zinc and ZAMAK also available.
"""


class _FakeCrawler:
    """In-memory crawler returning fixed text (no network)."""

    def __init__(self, text: str):
        self._text = text

    def crawl(self, url: str) -> CrawlResult:
        return CrawlResult(url=url, text_content=self._text, pages_crawled=1)


def _analyze(text: str = SAMPLE_HTML, url: str = "https://acme-castings.example.com"):
    return analyze_website(url, crawler=_FakeCrawler(text))


# ---------------------------------------------------------------------------
# Website extraction
# ---------------------------------------------------------------------------
def test_derive_company_name_from_url():
    assert derive_company_name("https://acme-castings.example.com") == "Acme Castings"
    assert derive_company_name("https://www.voltworks.com/") == "Voltworks"
    assert derive_company_name("") == ""


def test_website_extraction_populates_profile():
    result = _analyze()
    assert result.company_name == "Acme Castings"
    assert result.url == "https://acme-castings.example.com"
    assert result.description  # reason text derived from signals
    assert "aluminum" in result.detected_materials
    assert any("die casting" in p for p in result.detected_processes)
    assert any("automotive" in ind for ind in result.industries_served)
    assert result.products  # detected product terms
    assert result.business_type  # manufacturer-like
    assert result.recommended_contact_role  # role detector returns something


def test_empty_site_produces_low_confidence_profile():
    result = _analyze(text="Welcome to our website.")
    assert result.confidence_score <= 45  # little usable signal text
    assert result.lead_score <= 40


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------
def test_signal_detection_finds_buying_signals():
    result = _analyze()
    assert result.buying_signals  # matched procurement phrases / signal detail
    assert result.procurement_score > 0
    assert result.procurement_type


def test_supplier_opportunities_flagged_for_strong_signals():
    result = _analyze()
    # Sample text has heavy casting + manufacturing capability language.
    assert any("casting" in o.lower() for o in result.supplier_opportunities)


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------
def test_lead_score_deterministic_and_bounded():
    rich = compute_lead_score(
        procurement_score=85,
        materials=["aluminum", "zinc", "magnesium"],
        processes=["die casting", "cnc machining", "tooling"],
        buying_signals=["rfq", "looking for suppliers"],
    )
    poor = compute_lead_score(
        procurement_score=0, materials=[], processes=[], buying_signals=[]
    )
    assert 0 <= rich <= 100
    assert 0 <= poor <= 100
    assert rich > poor
    assert poor == 0


def test_confidence_score_grows_with_signal_text():
    from app.ai.procurement_signals import analyze_procurement_signals
    from app.discovery.analyzer import _confidence_score

    rich = _confidence_score(SAMPLE_HTML * 3, analyze_procurement_signals(SAMPLE_HTML * 3))
    thin = _confidence_score("hello", analyze_procurement_signals("hello"))
    assert rich >= thin
    assert 0 <= thin <= 100 and 0 <= rich <= 100


# ---------------------------------------------------------------------------
# API: analyze-url
# ---------------------------------------------------------------------------
def _fake_result(url: str = "https://acme-castings.example.com") -> DiscoveryResult:
    return _analyze(url=url)


def test_analyze_url_api_persists_discovery(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.api.discovery.analyze_website", lambda url: _fake_result(url))
    r = client.post("/discovery/analyze-url", json={"url": "https://acme-castings.example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["company_name"] == "Acme Castings"
    assert body["lead_score"] is not None
    assert body["recommended_contact_role"]
    assert body["lead_id"] is None
    assert "aluminum" in body["detected_materials"]

    # Persisted and listed.
    listed = client.get("/discovery").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_analyze_url_validation(client: TestClient):
    assert client.post("/discovery/analyze-url", json={}).status_code == 422
    r = client.post("/discovery/analyze-url", json={"url": "not-a-url"})
    assert r.status_code == 422
    assert "http" in r.json()["detail"]


def test_analyze_url_crawl_failure_returns_502(client: TestClient, monkeypatch):
    def boom(url):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.api.discovery.analyze_website", boom)
    r = client.post("/discovery/analyze-url", json={"url": "https://down.example.com"})
    assert r.status_code == 502
    assert "connection refused" in r.json()["detail"]


# ---------------------------------------------------------------------------
# API: add discovery to CRM
# ---------------------------------------------------------------------------
def test_add_to_crm_creates_lead(client: TestClient, db, monkeypatch):
    monkeypatch.setattr("app.api.discovery.analyze_website", lambda url: _fake_result(url))
    disc = client.post(
        "/discovery/analyze-url", json={"url": "https://acme-castings.example.com"}
    ).json()

    r = client.post(f"/discovery/{disc['id']}/lead")
    assert r.status_code == 201
    lead = r.json()
    assert lead["name"] == "Acme Castings"
    assert lead["lead_source"] == "discovery"
    assert lead["website"] == "https://acme-castings.example.com"
    assert "aluminum" in (lead["materials"] or "")
    assert lead["lead_score"] is not None

    # Already added -> 409.
    again = client.post(f"/discovery/{disc['id']}/lead")
    assert again.status_code == 409
    assert "already added" in again.json()["detail"]


def test_add_to_crm_dedup_by_website(client: TestClient, db, monkeypatch):
    # A lead already exists with this website.
    client.post(
        "/leads",
        json={"name": "Existing Co", "website": "https://acme-castings.example.com"},
    )
    monkeypatch.setattr("app.api.discovery.analyze_website", lambda url: _fake_result(url))
    disc = client.post(
        "/discovery/analyze-url", json={"url": "https://acme-castings.example.com"}
    ).json()

    r = client.post(f"/discovery/{disc['id']}/lead")
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_add_to_crm_unknown_discovery_404(client: TestClient):
    r = client.post("/discovery/999999/lead")
    assert r.status_code == 404
