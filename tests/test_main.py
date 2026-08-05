"""Smoke tests for the API using an in-memory SQLite database.

These tests do not require PostgreSQL, OpenAI, or Playwright.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def _make_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_health():
    client = _make_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root():
    client = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "docs" in resp.json()


def test_create_and_read_lead():
    client = _make_client()
    payload = {
        "name": "Acme Die Casting Co",
        "website": "https://acme.example.com",
        "industry": "Die casting",
        "country": "USA",
    }
    r = client.post("/leads", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "Acme Die Casting Co"
    lead_id = data["id"]

    got = client.get(f"/leads/{lead_id}")
    assert got.status_code == 200
    assert got.json()["website"] == "https://acme.example.com"


def test_duplicate_website_conflict():
    client = _make_client()
    payload = {"name": "Dup Inc", "website": "https://dup.example.com"}
    first = client.post("/leads", json=payload)
    assert first.status_code == 201
    second = client.post("/leads", json=payload)
    assert second.status_code == 409


def test_update_and_list():
    client = _make_client()
    created = client.post(
        "/leads", json={"name": "Beta Castings", "industry": "Die casting"}
    )
    lead_id = created.json()["id"]

    upd = client.patch(f"/leads/{lead_id}", json={"country": "Germany"})
    assert upd.status_code == 200
    assert upd.json()["country"] == "Germany"

    listing = client.get("/leads")
    assert listing.status_code == 200
    assert any(item["id"] == lead_id for item in listing.json())


def test_delete_lead():
    client = _make_client()
    created = client.post("/leads", json={"name": "Gamma Molds"})
    lead_id = created.json()["id"]

    deleted = client.delete(f"/leads/{lead_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/leads/{lead_id}")
    assert missing.status_code == 404


def test_delete_lead_with_draft():
    """Deleting a lead that has outreach drafts must not 500.

    Regression: the ORM's default delete tries to null the child FK, which
    fails for NOT NULL columns; FK children are now removed explicitly first.
    """
    client = _make_client()
    created = client.post(
        "/leads", json={"name": "Delta Castings", "industry": "automotive"}
    )
    lead_id = created.json()["id"]

    gen = client.post(f"/leads/{lead_id}/generate-email")
    assert gen.status_code in (200, 201), gen.text
    assert gen.json()["lead_id"] == lead_id

    deleted = client.delete(f"/leads/{lead_id}")
    assert deleted.status_code == 204
    assert client.get(f"/leads/{lead_id}").status_code == 404
    assert client.get("/outreach/drafts").json() == []


def test_analyze_rule_based_works_without_openai_key():
    client = _make_client()
    created = client.post(
        "/leads",
        json={
            "name": "Delta Components automotive EV aluminum",
            "industry": "Die casting",
        },
    )
    lead_id = created.json()["id"]
    # Phase 2.3 analysis is rule-based and works without an OpenAI key.
    resp = client.post(f"/leads/{lead_id}/analyze")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "casting_need_score" in data
    assert data["sales_priority"] in ("HIGH", "MEDIUM", "LOW")
    # The sample text contains automotive/EV/aluminum -> high score.
    assert data["casting_need_score"] >= 80
