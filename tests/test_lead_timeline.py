"""Phase 4.6 — Outreach Tracking and Lead Status Pipeline tests.

Covers:
  * the new lead status set + valid/invalid transitions via the API
  * outreach timeline creation (generated / approved / sent / replied events)
  * GET /leads/{id}/timeline response (newest first, message subjects attached)
  * API validation (404 unknown lead, 400 invalid status / transition)
"""
from fastapi.testclient import TestClient


def _make_lead(client, *, name="TL Co", contact_email=None):
    payload = {
        "name": name,
        "website": f"https://tl-{abs(hash(name))}.example.com",
        "industry": "automotive",
        "materials": "aluminum",
        "manufacturing_process": "high pressure die casting",
    }
    if contact_email:
        payload["contact_email"] = contact_email
    r = client.post("/leads", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------
def test_status_transition_chain(client: TestClient):
    """The full Phase 4.6 pipeline: new → qualified → sent → contacted →
    replied → rfq → customer → closed (each step valid)."""
    lead_id = _make_lead(client)
    for target in ["qualified", "sent", "contacted", "replied", "rfq", "customer", "closed"]:
        r = client.patch(f"/leads/{lead_id}/status", json={"lead_status": target})
        assert r.status_code == 200, f"{target} transition failed: {r.text}"
        assert r.json()["lead_status"] == target
        assert r.json()["last_activity_time"] is not None


def test_invalid_transition_rejected(client: TestClient):
    lead_id = _make_lead(client)
    # new -> contacted is not a valid direct move.
    r = client.patch(f"/leads/{lead_id}/status", json={"lead_status": "contacted"})
    assert r.status_code == 400
    assert "Invalid lead status transition" in r.json()["detail"]


def test_unknown_status_value_rejected(client: TestClient):
    lead_id = _make_lead(client)
    r = client.patch(f"/leads/{lead_id}/status", json={"lead_status": "bogus"})
    assert r.status_code == 400


def test_status_update_nonexistent_lead(client: TestClient):
    r = client.patch("/leads/999999/status", json={"lead_status": "qualified"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def test_timeline_unknown_lead_404(client: TestClient):
    r = client.get("/leads/999999/timeline")
    assert r.status_code == 404


def test_timeline_records_generated_approved_sent_replied(client: TestClient):
    lead_id = _make_lead(client, contact_email="buyer@timeline.com")

    # 1) generate an email -> 'generated' event
    gen = client.post(f"/leads/{lead_id}/generate-email")
    assert gen.status_code == 201
    message_id = gen.json()["id"]

    tl = client.get(f"/leads/{lead_id}/timeline").json()
    assert tl["lead_id"] == lead_id
    assert tl["lead_status"] == "new"
    assert [e["event_type"] for e in tl["events"]] == ["generated"]
    assert tl["events"][0]["message_id"] == message_id
    assert tl["events"][0]["message_subject"]  # decorated with subject

    # 2) release the draft -> 'approved' event
    client.patch(f"/outreach/drafts/{message_id}/gate", json={"gate_status": "ready"})
    tl = client.get(f"/leads/{lead_id}/timeline").json()
    types = [e["event_type"] for e in tl["events"]]
    assert types == ["approved", "generated"]

    # 3) send it -> 'sent' event + lead moves to sent
    s = client.post(f"/outreach/drafts/{message_id}/send")
    assert s.status_code == 200 and s.json()["success"] is True
    tl = client.get(f"/leads/{lead_id}/timeline").json()
    types = [e["event_type"] for e in tl["events"]]
    assert types == ["sent", "approved", "generated"]  # newest first
    sent_event = tl["events"][0]
    assert sent_event["message_id"] == message_id
    assert tl["lead_status"] == "sent"

    # 4) mark replied -> 'replied' event on the timeline
    r = client.patch(f"/leads/{lead_id}/status", json={"lead_status": "replied"})
    assert r.status_code == 200
    tl = client.get(f"/leads/{lead_id}/timeline").json()
    types = [e["event_type"] for e in tl["events"]]
    assert types == ["replied", "sent", "approved", "generated"]
    assert tl["events"][0]["message_id"] == message_id
    assert tl["lead_status"] == "replied"


def test_timeline_empty_for_new_lead(client: TestClient):
    lead_id = _make_lead(client)
    tl = client.get(f"/leads/{lead_id}/timeline").json()
    assert tl["events"] == []
    assert tl["lead_status"] == "new"
