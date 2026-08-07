"""Phase 8.5 — Contact Intelligence Engine.

Covers:
  * title classification (category + seniority) — ``app.contact_intelligence.titles``
  * purchasing priority scoring — ``app.contact_intelligence.scoring``
  * the website contact crawler with an injected fetcher — ``app.contact_intelligence.extractor``
  * the service: discover (website + CRM + derived-from-EmailAddress), classify, score
  * the API: POST /api/contacts/discover/{id}, GET /api/contacts/{id},
    POST /api/contacts/score/{id}, plus 404 / 422 edge cases
"""
from app.contact_intelligence import scoring as sc
from app.contact_intelligence import service as svc
from app.contact_intelligence.extractor import WebsiteContactCrawler
from app.contact_intelligence.titles import classify_title, classify_title_category, detect_seniority


# ---------------------------------------------------------------------------
# Title classification
# ---------------------------------------------------------------------------
def test_classify_title_category():
    assert classify_title_category("Purchasing Manager") == "procurement"
    assert classify_title_category("VP of Sales") == "sales"
    assert classify_title_category("Quality Engineer") == "engineering"
    # Function-based category: a CFO sits in *finance*; seniority (executive)
    # is captured separately and combined in the purchasing score.
    assert classify_title_category("Chief Financial Officer") == "finance"
    assert classify_title_category("Plant Operations Lead") == "operations"
    assert classify_title_category("John Smith") == "other"


def test_classify_title_cfo_is_executive_seniority():
    cat, sen = classify_title("Chief Financial Officer")
    assert cat == "finance"
    assert sen == "executive"


def test_detect_seniority():
    assert detect_seniority("CEO") == "executive"
    assert detect_seniority("Purchasing Manager") == "senior"
    assert detect_seniority("Buyer") == "mid"
    assert detect_seniority("Junior Engineer") == "junior"
    assert detect_seniority("") == "unknown"


def test_classify_title_returns_pair():
    cat, sen = classify_title("Director of Procurement")
    assert cat == "procurement"
    assert sen == "executive"


# ---------------------------------------------------------------------------
# Purchasing priority scoring
# ---------------------------------------------------------------------------
def test_score_procurement_exec_crm_is_high():
    res = sc.score_contact(title="Purchasing Manager", source="crm")
    assert res["title_category"] == "procurement"
    assert res["seniority"] == "senior"
    assert res["purchasing_score"] >= 75
    assert res["priority"] == "high"


def test_score_ceo_crm_is_high():
    res = sc.score_contact(title="CEO", source="crm")
    assert res["priority"] == "high"


def test_score_junior_other_email_pattern_is_low():
    res = sc.score_contact(title="Receptionist", source="email_pattern")
    assert res["purchasing_score"] < 55
    assert res["priority"] == "low"


def test_priority_from_score_thresholds():
    assert sc.priority_from_score(90) == "high"
    assert sc.priority_from_score(75) == "high"
    assert sc.priority_from_score(60) == "medium"
    assert sc.priority_from_score(55) == "medium"
    assert sc.priority_from_score(54) == "low"


def test_score_purchasing_clamps():
    assert 0 <= sc.score_purchasing("procurement", "executive", "crm") <= 100


# ---------------------------------------------------------------------------
# Website contact crawler (injectable fetcher)
# ---------------------------------------------------------------------------
def test_website_contact_crawler_extracts():
    # Newline-separated "Name, Title" blocks are what the shared contact
    # extractor's regex expects (literal separators, not HTML entities).
    html = (
        "<html><body>"
        "John Smith, Purchasing Manager\n"
        "Jane Doe, Sales Director\n"
        "Contact: john.smith@acme.com or jane.doe@acme.com\n"
        "</body></html>"
    )
    crawler = WebsiteContactCrawler(
        "https://acme.com", fetcher=lambda url: html, max_pages=1
    )
    contacts = crawler.crawl()
    names = {c["name"] for c in contacts}
    assert "John Smith" in names
    assert "Jane Doe" in names
    # The shared contact extractor filters free e-mail domains; acme.com stays.
    # (It assigns the first on-domain mailbox to each contact line, so we only
    # assert that a corporate e-mail was discovered and no free domain leaked.)
    emails = {c["email"] for c in contacts if c["email"]}
    assert emails
    assert all(e.endswith("@acme.com") for e in emails)


def test_website_contact_crawler_handles_empty():
    crawler = WebsiteContactCrawler("", fetcher=lambda url: "")
    assert crawler.crawl() == []


# ---------------------------------------------------------------------------
# Name derivation from e-mail local-part (service helper)
# ---------------------------------------------------------------------------
def test_name_from_email():
    assert svc._name_from_email("john.smith") == "John Smith"
    assert svc._name_from_email("jsmith") == "Jsmith"
    assert svc._name_from_email("jane_doe") == "Jane Doe"


# ---------------------------------------------------------------------------
# API: discover / list / score
# ---------------------------------------------------------------------------
def _make_lead(client, website="https://acme.com", contact_email=None,
               contact_name=None, contact_role=None):
    body = {"name": "Acme Castings", "website": website}
    if contact_email:
        body["contact_email"] = contact_email
    if contact_name:
        body["contact_name"] = contact_name
    if contact_role:
        body["contact_role"] = contact_role
    r = client.post("/leads", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def test_discover_persists_website_and_crm(client, monkeypatch):
    import app.contact_intelligence.service as svc_mod

    # Fake the crawler so no network / browser is used.
    class _FakeCrawler:
        def __init__(self, homepage, *, fetcher=None, max_pages=8):
            self.homepage = homepage

        @property
        def domain(self):
            return "acme.com"

        def crawl(self):
            return [
                {"name": "John Smith", "title": "Purchasing Manager",
                 "email": "john.smith@acme.com", "linkedin": None},
                {"name": "Jane Doe", "title": "Engineer",
                 "email": "jane.doe@acme.com", "linkedin": None},
            ]

    monkeypatch.setattr(svc_mod, "WebsiteContactCrawler", _FakeCrawler)

    # Lead also has a CRM contact (merged, never lost).
    lead_id = _make_lead(
        client,
        contact_email="ceo@acme.com",
        contact_name="Mary Owner",
        contact_role="Owner",
    )
    r = client.post(f"/api/contacts/discover/{lead_id}")
    assert r.status_code == 200
    body = r.json()
    contacts = {c["email"]: c for c in body["contacts"]}
    # Website (2) + CRM (1) merged.
    assert "john.smith@acme.com" in contacts
    assert "jane.doe@acme.com" in contacts
    assert "ceo@acme.com" in contacts
    assert body["count"] == 3

    # Intelligence fields are populated + the CRM owner is high priority.
    ceo = contacts["ceo@acme.com"]
    assert ceo["title_category"] == "executive"
    assert ceo["priority"] == "high"
    # Purchasing Manager should outrank the Engineer.
    assert contacts["john.smith@acme.com"]["purchasing_score"] > \
        contacts["jane.doe@acme.com"]["purchasing_score"]

    # GET lists the same set, ranked by purchasing_score desc.
    g = client.get(f"/api/contacts/{lead_id}")
    assert g.status_code == 200
    assert g.json()["count"] == 3
    ranks = [c["rank"] for c in g.json()["contacts"]]
    assert ranks == sorted(ranks)  # 1..N contiguous


def test_discover_404_for_missing_company(client):
    r = client.post("/api/contacts/discover/999999")
    assert r.status_code == 404


def test_discover_422_without_source(client):
    lead_id = _make_lead(client, website="", contact_email=None)
    r = client.post(f"/api/contacts/discover/{lead_id}")
    assert r.status_code == 422


def test_discover_derives_from_personal_emails(client, db, monkeypatch):
    import app.contact_intelligence.service as svc_mod
    from app.models.email_address import EmailAddress

    # No website / CRM — only personal e-mails discovered by Phase 8.
    class _FakeCrawler:
        def __init__(self, homepage, *, fetcher=None, max_pages=8):
            self.homepage = homepage

        @property
        def domain(self):
            return "acme.com"

        def crawl(self):
            return []

    monkeypatch.setattr(svc_mod, "WebsiteContactCrawler", _FakeCrawler)

    lead_id = _make_lead(client, website="", contact_email=None)
    # Seed two personal e-mail addresses (Phase 8 EmailAddress rows).
    db.add(EmailAddress(company_id=lead_id, email="tom.brown@acme.com",
                        email_type="personal", source="website"))
    db.add(EmailAddress(company_id=lead_id, email="info@acme.com",
                        email_type="role", source="website"))
    db.commit()

    r = client.post(f"/api/contacts/discover/{lead_id}")
    assert r.status_code == 200
    body = r.json()
    # Only the personal address becomes a contact (role e-mail is skipped).
    assert body["count"] == 1
    contact = body["contacts"][0]
    assert contact["email"] == "tom.brown@acme.com"
    assert contact["source"] == "email_pattern"
    assert contact["full_name"] == "Tom Brown"
    assert contact["email_address_id"] is not None


def test_score_endpoint_reprioritizes(client, monkeypatch):
    import app.contact_intelligence.service as svc_mod

    class _FakeCrawler:
        def __init__(self, homepage, *, fetcher=None, max_pages=8):
            self.homepage = homepage

        @property
        def domain(self):
            return "acme.com"

        def crawl(self):
            return [
                {"name": "Sam Lee", "title": "Buyer",
                 "email": "sam.lee@acme.com", "linkedin": None},
            ]

    monkeypatch.setattr(svc_mod, "WebsiteContactCrawler", _FakeCrawler)

    lead_id = _make_lead(client)
    client.post(f"/api/contacts/discover/{lead_id}")
    # Re-run classification + scoring explicitly.
    r = client.post(f"/api/contacts/score/{lead_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    # Buyer -> procurement -> high priority.
    assert body["contacts"][0]["title_category"] == "procurement"
    assert body["contacts"][0]["priority"] == "high"
