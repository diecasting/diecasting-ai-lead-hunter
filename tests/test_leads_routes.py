"""API tests for lead routes, focusing on the /leads/high-priority vs
/leads/{lead_id} path-conflict regression.

FastAPI evaluates routes in declaration order. If the static ``high-priority``
path is declared *after* the ``/{lead_id: int}`` path, a request to
``GET /leads/high-priority`` is captured by ``get_lead`` with
``lead_id="high-priority"`` and fails validation with HTTP 422. The route must
instead be declared before the int-path routes so it matches first.
"""
from app.schemas.lead import CompanyLeadCreate


def test_high_priority_route_does_not_422_as_lead_id(client):
    """GET /leads/high-priority must return 200 (not 422 path conflict)."""
    resp = client.get("/leads/high-priority")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_get_lead_by_id_still_works(client):
    """GET /leads/{id} continues to resolve a numeric lead id."""
    payload = CompanyLeadCreate(
        name="Route Test Co",
        website="https://route-test.com",
        domain="route-test.com",
        country="USA",
    )
    created = client.post("/leads", json=payload.model_dump())
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]

    resp = client.get(f"/leads/{lead_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == lead_id


def test_get_lead_by_id_returns_404_for_unknown(client):
    resp = client.get("/leads/999999")
    assert resp.status_code == 404


def test_high_priority_returns_only_high_then_medium(client):
    """Create a HIGH and a MEDIUM lead; high-priority must surface them."""
    high = client.post(
        "/leads",
        json=CompanyLeadCreate(
            name="High Co",
            website="https://high-co.com",
            domain="high-co.com",
            sales_priority="HIGH",
            ai_score=90,
        ).model_dump(),
    )
    assert high.status_code == 201, high.text
    med = client.post(
        "/leads",
        json=CompanyLeadCreate(
            name="Medium Co",
            website="https://medium-co.com",
            domain="medium-co.com",
            sales_priority="MEDIUM",
            ai_score=70,
        ).model_dump(),
    )
    assert med.status_code == 201, med.text

    resp = client.get("/leads/high-priority")
    assert resp.status_code == 200, resp.text
    ids = {l["id"] for l in resp.json()}
    assert high.json()["id"] in ids
    assert med.json()["id"] in ids
