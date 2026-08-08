"""Phase 11: Sales Pipeline Opportunity Engine tests.

Covers:
  * opportunity CRUD (create / list / get / stage transition)
  * stage history audit rows
  * reply-driven automation: a classified ``rfq_request`` creates an Opportunity
  * weighted pipeline summary calculation
  * unchanged Phase 6 / 10 contracts (unknown / spam still produce no Opportunity)
"""
from app.models.opportunity import Opportunity


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _make_lead(client, name="PipeCo"):
    r = client.post(
        "/leads",
        json={
            "name": name,
            "website": f"https://{name.lower()}.example.com",
            "contact_email": "buyer@pipe.example.com",
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def _post_opp(client, company_id, **kw):
    body = {"company_id": company_id, **kw}
    r = client.post("/api/pipeline/opportunities", json=body)
    return r


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def test_create_and_get_opportunity(client):
    lid = _make_lead(client, "CrudCo")
    r = _post_opp(
        client, lid,
        stage="prospecting", amount=12000.0, probability=40,
        currency="USD", priority="high", owner="alice",
    )
    assert r.status_code == 201
    data = r.json()
    assert data["id"] > 0
    assert data["stage"] == "prospecting"
    assert data["amount"] == 12000.0
    assert data["probability"] == 40
    assert data["currency"] == "USD"
    # creation records exactly one history row.
    assert len(data["stage_history"]) == 1
    assert data["stage_history"][0]["from_stage"] is None
    assert data["stage_history"][0]["to_stage"] == "prospecting"

    got = client.get(f"/api/pipeline/opportunities/{data['id']}")
    assert got.status_code == 200
    assert got.json()["owner"] == "alice"


def test_create_opportunity_validation(client):
    lid = _make_lead(client, "ValCo")
    # bad stage -> 422
    assert _post_opp(client, lid, stage="negotiating").status_code == 422
    # bad priority -> 422
    assert _post_opp(client, lid, priority="critical").status_code == 422
    # probability out of range -> 422
    assert _post_opp(client, lid, probability=150).status_code == 422


def test_list_opportunities_filters(client):
    lid = _make_lead(client, "ListCo")
    a = _post_opp(client, lid, stage="prospecting", probability=30).json()
    _post_opp(client, lid, stage="won", probability=100).json()

    # filter by stage
    rows = client.get("/api/pipeline/opportunities?stage=prospecting").json()
    assert all(o["stage"] == "prospecting" for o in rows)
    assert len(rows) == 1 and rows[0]["id"] == a["id"]

    # filter by status=open excludes won/lost
    rows = client.get("/api/pipeline/opportunities?status=open").json()
    assert all(o["stage"] not in ("won", "lost") for o in rows)
    assert any(o["id"] == a["id"] for o in rows)

    # filter by company
    rows = client.get(f"/api/pipeline/opportunities?company_id={lid}").json()
    assert len(rows) == 2


def test_stage_transition_records_history(client):
    lid = _make_lead(client, "StageCo")
    opp = _post_opp(client, lid, stage="prospecting", probability=20).json()

    # transition to negotiation
    r = client.put(
        f"/api/pipeline/opportunities/{opp['id']}/stage",
        json={"stage": "negotiation", "note": "Customer negotiating terms"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["stage"] == "negotiation"
    assert len(data["stage_history"]) == 2
    second = data["stage_history"][1]
    assert second["from_stage"] == "prospecting"
    assert second["to_stage"] == "negotiation"
    assert second["note"] == "Customer negotiating terms"
    # probability is left under manual control (not auto-overwritten).
    assert data["probability"] == 20

    # transition to won sets actual_close_date
    r = client.put(
        f"/api/pipeline/opportunities/{opp['id']}/stage",
        json={"stage": "won"},
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "won"
    assert r.json()["actual_close_date"] is not None

    # invalid stage -> 422
    bad = client.put(
        f"/api/pipeline/opportunities/{opp['id']}/stage",
        json={"stage": "bogus"},
    )
    assert bad.status_code == 422

    # unknown id -> 404
    assert client.put(
        "/api/pipeline/opportunities/999999/stage", json={"stage": "won"}
    ).status_code == 404


# ---------------------------------------------------------------------------
# Reply-driven automation (rfq_request -> Opportunity)
# ---------------------------------------------------------------------------
def test_rfq_reply_creates_opportunity(client):
    lid = _make_lead(client, "RfqPipeCo")
    r = client.post(
        "/outreach/replies/analyze",
        json={
            "lead_id": lid,
            "reply_text": (
                "Please send us a quote, we have an open RFQ for die cast "
                "housings in ADC12, qty 5000 pcs, urgent."
            ),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "rfq_request"
    assert any("opportunity created" in a for a in body["applied_actions"])

    rows = client.get(f"/api/pipeline/opportunities?company_id={lid}").json()
    assert len(rows) == 1
    opp = rows[0]
    # Deterministic baseline: qualification stage (25) + urgency (+10) + qty (+5)
    assert opp["stage"] == "qualification"
    assert opp["probability"] == 40
    assert opp["amount"] is None  # never guessed without AI
    assert opp["currency"] == "USD"
    assert opp["rfq_id"] is not None
    assert opp["reply_id"] is not None


def test_unknown_reply_creates_no_opportunity(client):
    lid = _make_lead(client, "NoOppCo")
    r = client.post(
        "/outreach/replies/analyze",
        json={"lead_id": lid, "reply_text": "Thanks."},
    )
    assert r.status_code == 200
    assert r.json()["intent"] == "unknown"
    # No opportunity may be created for a pure-noise reply.
    rows = client.get(f"/api/pipeline/opportunities?company_id={lid}").json()
    assert rows == []


# ---------------------------------------------------------------------------
# Weighted pipeline summary
# ---------------------------------------------------------------------------
def test_weighted_pipeline_summary(client):
    lid = _make_lead(client, "SummaryCo")

    # open prospecting: 1000 @ 50% -> 500
    _post_opp(client, lid, stage="prospecting", amount=1000.0, probability=50)
    # open negotiation: 2000 @ 100% -> 2000
    _post_opp(client, lid, stage="negotiation", amount=2000.0, probability=100)
    # won: 5000 (full value, not weighted)
    _post_opp(client, lid, stage="won", amount=5000.0, probability=100)
    # lost: 300
    _post_opp(client, lid, stage="lost", amount=300.0, probability=0)

    s = client.get("/api/pipeline/summary").json()
    assert s["total_open"] == 2
    assert s["total_open_value"] == 3000.0
    assert s["weighted_value"] == 2500.0
    assert s["weighted_value_by_currency"]["USD"] == 2500.0
    assert s["won_count"] == 1
    assert s["won_value"] == 5000.0
    assert s["lost_count"] == 1
    assert s["lost_value"] == 300.0
    assert s["by_stage"]["prospecting"] == 1
    assert s["by_stage"]["negotiation"] == 1
    assert s["by_stage"]["won"] == 1
    assert s["by_stage"]["lost"] == 1


def test_weighted_pipeline_default_probability(client):
    """Open opportunity without an explicit probability uses the stage baseline."""
    lid = _make_lead(client, "DefProbCo")
    # proposal baseline probability is 50%; amount 800 -> weighted 400.
    _post_opp(client, lid, stage="proposal", amount=800.0)

    s = client.get("/api/pipeline/summary").json()
    assert s["weighted_value"] == 400.0
