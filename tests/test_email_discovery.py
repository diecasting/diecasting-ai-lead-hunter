"""Phase 8 — Email Discovery & Verification Engine.

Covers:
  * pattern inference + role/personal classification (``app.email_discovery.patterns``)
  * contact e-mail ranking (``app.email_discovery.ranking``)
  * the website crawler with an injected fetcher (``app.email_discovery.extractor``)
  * the verification pipeline: syntax / disposable / MX / SMTP / catch-all
    (``app.email_discovery.verification``) — all offline with fakes
  * the API: POST /api/email/discover/{id}, POST /api/email/verify,
    GET /api/email/{id}, plus 404 / 422 edge cases
"""
from app.email_discovery import patterns as pat
from app.email_discovery import ranking as rnk
from app.email_discovery.extractor import WebsiteEmailCrawler
from app.email_discovery.verification import verify_email_address


# ---------------------------------------------------------------------------
# Pattern inference + classification
# ---------------------------------------------------------------------------
def test_classify_email_type():
    assert pat.classify_email_type("sales@example.com") == "role"
    assert pat.classify_email_type("john.smith@example.com") == "personal"
    assert pat.classify_email_type("buyer123@example.com") == "generic"


def test_infer_patterns_from_known():
    known = ["john.smith@acme.com", "jane.doe@acme.com", "bob@acme.com"]
    result = pat.infer_patterns(known, "acme.com")
    assert "first.last" in result
    assert "first" in result
    # first.last observed twice, first once -> first.last ranks first.
    assert result[0] == "first.last"


def test_infer_patterns_fallback_when_empty():
    result = pat.infer_patterns([], "acme.com")
    assert result == ["first.last", "first"]


def test_generate_pattern_emails():
    patterns = ["first.last", "first", "firstlast", "flast", "firstl"]
    out = pat.generate_pattern_emails(patterns, "John", "Smith", domain="acme.com")
    assert "john.smith@acme.com" in out
    assert "john@acme.com" in out
    assert "johnsmith@acme.com" in out
    assert "jsmith@acme.com" in out
    assert "johns@acme.com" in out


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def test_rank_personal_beats_role():
    personal = rnk.rank_score("john.smith@acme.com", email_type="personal")
    role = rnk.rank_score("sales@acme.com", email_type="role")
    assert personal > role


def test_rank_pattern_capped():
    guessed = rnk.rank_score(
        "john.smith@acme.com", email_type="personal", source="pattern"
    )
    assert guessed <= 35


def test_rank_blends_verification_score():
    # A verified-valid personal address should outrank an unverified personal one.
    verified = rnk.rank_score(
        "john.smith@acme.com",
        email_type="personal",
        verification_status="valid",
        verification_score=95,
    )
    unverified = rnk.rank_score("john.smith@acme.com", email_type="personal")
    assert verified > unverified


# ---------------------------------------------------------------------------
# Website crawler (injectable fetcher)
# ---------------------------------------------------------------------------
def test_website_crawler_extracts_on_domain():
    html = (
        '<html><body>Contact us at sales@acme.com or john.smith@acme.com. '
        'Spam: bob@gmail.com ignore@test.com</body></html>'
    )
    crawler = WebsiteEmailCrawler(
        "https://acme.com", fetcher=lambda url: html, max_pages=1
    )
    emails = crawler.crawl()
    assert "sales@acme.com" in emails
    assert "john.smith@acme.com" in emails
    # Free / test domains are filtered out by the shared extractor.
    assert "bob@gmail.com" not in emails
    assert "ignore@test.com" not in emails


def test_website_crawler_handles_empty():
    crawler = WebsiteEmailCrawler("", fetcher=lambda url: "")
    assert crawler.crawl() == []


# ---------------------------------------------------------------------------
# Verification pipeline (offline fakes)
# ---------------------------------------------------------------------------
def test_verify_syntax_invalid():
    res = verify_email_address("not-an-email")
    assert res.status == "invalid"
    assert res.score == 0


def test_verify_no_mx_is_invalid():
    res = verify_email_address("buyer@nodomain.example", mx_resolver=lambda d: [])
    assert res.status == "invalid"
    assert "no MX" in res.reason


def test_verify_inconclusive_mx_is_unknown():
    res = verify_email_address(
        "buyer@unknown.example", mx_resolver=lambda d: None
    )
    assert res.status == "unknown"
    assert res.is_deliverable == "unknown"


def test_verify_mx_ok_smtp_deliverable_is_valid():
    res = verify_email_address(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "deliverable",
        catch_all_enabled=False,
    )
    assert res.status == "valid"
    assert res.score == 95
    assert res.catch_all is False


def test_verify_mx_ok_smtp_undeliverable_is_invalid():
    res = verify_email_address(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "undeliverable",
    )
    assert res.status == "invalid"


def test_verify_disposable_downgrades():
    res = verify_email_address(
        "info@mailinator.com",
        mx_resolver=lambda d: ["mx.mailinator.com"],
        smtp_check=lambda h, e: "unknown",
    )
    assert res.status == "unknown"
    assert res.score <= 30


def test_verify_catch_all_detected_and_softens():
    # SMTP returns deliverable for everything => catch-all domain.
    res = verify_email_address(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "deliverable",
        catch_all_enabled=True,
    )
    assert res.catch_all is True
    assert res.status == "unknown"  # caught-all softens a valid verdict
    assert res.score < 95


def test_verify_catch_all_disabled():
    res = verify_email_address(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "deliverable",
        catch_all_enabled=False,
    )
    assert res.catch_all is False
    assert res.status == "valid"


# ---------------------------------------------------------------------------
# API: discover / verify / list
# ---------------------------------------------------------------------------
def _make_lead(client, website="https://acme.com", contact_email=None):
    body = {"name": "Acme Castings", "website": website}
    if contact_email:
        body["contact_email"] = contact_email
    r = client.post("/leads", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def test_discover_persists_website_and_crm_emails(client, monkeypatch):
    import app.email_discovery.service as svc

    # Fake the crawler so no network / browser is used.
    class _FakeCrawler:
        def __init__(self, homepage, *, fetcher=None, max_pages=8):
            self.homepage = homepage

        @property
        def domain(self):
            return "acme.com"

        def crawl(self):
            return ["sales@acme.com", "john.smith@acme.com", "info@acme.com"]

    monkeypatch.setattr(svc, "WebsiteEmailCrawler", _FakeCrawler)

    lead_id = _make_lead(client, contact_email="ceo@acme.com")
    r = client.post(f"/api/email/discover/{lead_id}")
    assert r.status_code == 200
    body = r.json()
    emails = {e["email"] for e in body["emails"]}
    # Website-found (3) + CRM (1) merged.
    assert "sales@acme.com" in emails
    assert "john.smith@acme.com" in emails
    assert "info@acme.com" in emails
    assert "ceo@acme.com" in emails
    # Patterns inferred from the known addresses.
    assert "first.last" in body["patterns"]
    # Highest-ranked should be the personal address.
    assert body["emails"][0]["email_type"] == "personal"

    # GET lists the same set, ranked.
    g = client.get(f"/api/email/{lead_id}")
    assert g.status_code == 200
    assert g.json()["count"] == 4


def test_discover_404_for_missing_company(client):
    r = client.post("/api/email/discover/999999")
    assert r.status_code == 404


def test_discover_422_without_source(client):
    lead_id = _make_lead(client, website="", contact_email=None)
    r = client.post(f"/api/email/discover/{lead_id}")
    assert r.status_code == 422


def test_verify_endpoint_verifies_and_persists(client, monkeypatch):
    import app.email_discovery.service as svc
    import app.outreach.lead_email_verifier as lev

    # Stub the crawler so no network / browser is used.
    class _FakeCrawler:
        def __init__(self, homepage, *, fetcher=None, max_pages=8):
            self.homepage = homepage

        @property
        def domain(self):
            return "acme.com"

        def crawl(self):
            return []

    monkeypatch.setattr(svc, "WebsiteEmailCrawler", _FakeCrawler)

    # SMTP probe: deliverable for normal addresses, unknown for the catch-all
    # random probe (no dot, 12-alpha local part) => not a catch-all domain.
    def fake_smtp(host, email):
        local = email.split("@", 1)[0]
        if "." not in local and len(local) == 12:
            return "unknown"
        return "deliverable"

    monkeypatch.setattr(lev, "smtp_probe", fake_smtp)
    # resolve_mx is already patched by conftest to return ["mx.example.com"].

    lead_id = _make_lead(client, contact_email="buyer@acme.com")
    # Discover first (so an EmailAddress row exists), then verify explicitly.
    client.post(f"/api/email/discover/{lead_id}")
    r = client.post("/api/email/verify", json={"company_id": lead_id})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    result = body["results"][0]
    assert result["verification_status"] == "valid"
    assert result["catch_all"] is False
    assert any(c["verifier"] == "mx" for c in result["checks"])

    # The persisted row reflects the verdict.
    g = client.get(f"/api/email/{lead_id}").json()
    assert g["emails"][0]["verification_status"] == "valid"


def test_verify_explicit_emails(client):
    r = client.post(
        "/api/email/verify",
        json={"emails": ["someone@external.com"]},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_verify_requires_input(client):
    r = client.post("/api/email/verify", json={})
    assert r.status_code == 422
