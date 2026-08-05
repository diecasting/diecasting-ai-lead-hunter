"""Phase 6 Stage 1 — AI Follow-up Automation Engine tests.

Covers:
  * sequence creation        — POST /outreach/sequences (+ validation)
  * scheduling               — after a send, follow-ups are auto-scheduled
                               (default 2-step cadence), idempotent
  * reply stops follow-up    — lead status replied/rfq/customer/closed cancels
  * follow-up generation     — due follow-ups render draft messages
  * status transitions       — pending → generated → sent; pause/resume
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _make_sent_draft(client, *, name="FollowCo", contact_email="buyer@followco.com"):
    """Create a lead, generate + release + send an email (mock provider)."""
    lead = client.post(
        "/leads",
        json={
            "name": name,
            "website": f"https://{name.lower()}.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "contact_email": contact_email,
        },
    )
    lead_id = lead.json()["id"]
    gen = client.post(f"/leads/{lead_id}/generate-email")
    message_id = gen.json()["id"]
    client.patch(f"/outreach/drafts/{message_id}/gate", json={"gate_status": "ready"})
    s = client.post(f"/outreach/drafts/{message_id}/send")
    assert s.status_code == 200 and s.json()["success"] is True
    return lead_id, message_id


def _make_sequence(client, **kw):
    payload = {
        "name": kw.get("name", "Default Cadence"),
        "steps": [
            {"delay_days": 3, "template": "technical_followup"},
            {"delay_days": 7, "template": "rfq_followup"},
        ],
    }
    payload.update(kw)
    r = client.post("/outreach/sequences", json=payload)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
def test_sequence_creation_and_list(client: TestClient):
    seq = _make_sequence(client)
    assert seq["name"] == "Default Cadence"
    assert seq["enabled"] is True
    assert seq["steps"] == [
        {"delay_days": 3, "template": "technical_followup"},
        {"delay_days": 7, "template": "rfq_followup"},
    ]

    listed = client.get("/outreach/sequences").json()
    assert any(s["id"] == seq["id"] for s in listed)


def test_sequence_validation(client: TestClient):
    base = {"name": "Bad", "steps": [{"delay_days": 3, "template": "technical_followup"}]}
    assert client.post("/outreach/sequences", json={"name": "", "steps": base["steps"]}).status_code == 422
    assert client.post("/outreach/sequences", json={**base, "steps": []}).status_code == 422
    assert client.post(
        "/outreach/sequences",
        json={**base, "steps": [{"delay_days": 0, "template": "technical_followup"}]},
    ).status_code == 422
    assert client.post(
        "/outreach/sequences",
        json={**base, "steps": [{"delay_days": 3, "template": "nope_template"}]},
    ).status_code == 422


def test_sequence_pause_resume(client: TestClient):
    seq = _make_sequence(client)
    off = client.patch(f"/outreach/sequences/{seq['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False
    on = client.patch(f"/outreach/sequences/{seq['id']}", json={"enabled": True}).json()
    assert on["enabled"] is True
    assert client.patch("/outreach/sequences/999999", json={"enabled": True}).status_code == 404


# ---------------------------------------------------------------------------
# Scheduling after send
# ---------------------------------------------------------------------------
def test_send_auto_schedules_followups(client: TestClient):
    lead_id, message_id = _make_sent_draft(client)

    followups = client.get(f"/outreach/followups?lead_id={lead_id}").json()
    assert len(followups) == 2  # default 2-step cadence
    assert [f["status"] for f in followups] == ["pending", "pending"]
    assert [f["step_number"] for f in followups] == [1, 2]
    assert followups[0]["original_message_id"] == message_id
    assert followups[0]["lead_name"] == "FollowCo"
    # Delay deltas: step 1 at +3d, step 2 at +7d (SQLite returns naive UTC).
    now = datetime.utcnow()
    d1 = datetime.fromisoformat(followups[0]["scheduled_at"])
    d2 = datetime.fromisoformat(followups[1]["scheduled_at"])
    assert abs((d1 - now).total_seconds() - 3 * 86400) < 120
    assert abs((d2 - d1).total_seconds() - 4 * 86400) < 120


def test_scheduling_idempotent(client: TestClient, db):
    lead_id, message_id = _make_sent_draft(client)
    before = len(client.get(f"/outreach/followups?lead_id={lead_id}").json())
    assert before == 2

    # start-followup again with the same original message -> no duplicates.
    again = client.post(
        f"/outreach/leads/{lead_id}/start-followup",
        json={"original_message_id": message_id},
    )
    assert again.status_code == 200
    assert again.json() == []

    after = len(client.get(f"/outreach/followups?lead_id={lead_id}").json())
    assert after == before


def test_start_followup_with_custom_sequence(client: TestClient):
    seq = _make_sequence(client, name="Custom 3-step")
    seq2 = client.patch(
        f"/outreach/sequences/{seq['id']}",
        json={"steps": [
            {"delay_days": 1, "template": "value_prop_followup"},
            {"delay_days": 4, "template": "technical_followup"},
            {"delay_days": 10, "template": "rfq_followup"},
        ]},
    ).json()

    lead_id, message_id = _make_sent_draft(client, name="CustomSeqCo")
    rows = client.post(
        f"/outreach/leads/{lead_id}/start-followup",
        json={"sequence_id": seq2["id"]},
    ).json()
    assert len(rows) == 3
    assert [r["step_number"] for r in rows] == [1, 2, 3]
    assert rows[0]["sequence_id"] == seq2["id"]


# ---------------------------------------------------------------------------
# Processing due follow-ups
# ---------------------------------------------------------------------------
def _force_due(client, db, lead_id):
    """Push every pending follow-up for the lead into the past."""
    rows = client.get(f"/outreach/followups?lead_id={lead_id}").json()
    from app.models.followup import OutreachFollowUp

    for r in rows:
        fu = db.query(OutreachFollowUp).filter(OutreachFollowUp.id == r["id"]).first()
        fu.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.add(fu)
    db.commit()
    return rows


def test_process_due_generates_and_sends(client: TestClient, db):
    lead_id, _ = _make_sent_draft(client, name="DueCo")
    _force_due(client, db, lead_id)

    r = client.post("/outreach/followups/process")
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] == 2
    assert body["sent"] == 2
    assert body["cancelled"] == 0

    followups = client.get(f"/outreach/followups?lead_id={lead_id}").json()
    assert all(f["status"] == "sent" for f in followups)
    # The generated follow-up messages are drafts -> sent, flagged follow-ups.
    from app.crud import outreach as oc

    msgs = oc.get_by_lead(db, lead_id)
    followup_msgs = [m for m in msgs if m.is_followup]
    assert len(followup_msgs) == 2
    assert all(m.status == "sent" for m in followup_msgs)
    assert {m.followup_seq for m in followup_msgs} == {1, 2}
    assert all(m.subject.startswith("Re:") for m in followup_msgs)


def test_reply_stops_followup(client: TestClient, db):
    lead_id, _ = _make_sent_draft(client, name="RepliedCo")
    _force_due(client, db, lead_id)
    # Lead replied -> follow-ups must be cancelled, not sent.
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "replied"})

    r = client.post("/outreach/followups/process")
    body = r.json()
    assert body["cancelled"] == 2
    assert body["sent"] == 0

    followups = client.get(f"/outreach/followups?lead_id={lead_id}").json()
    assert all(f["status"] == "cancelled" for f in followups)


def test_customer_stops_followup(client: TestClient, db):
    lead_id, _ = _make_sent_draft(client, name="CustomerCo")
    _force_due(client, db, lead_id)
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "qualified"})
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "sent"})
    # sent -> contacted -> replied -> rfq -> customer
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "contacted"})
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "replied"})
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "rfq"})
    client.patch(f"/leads/{lead_id}/status", json={"lead_status": "customer"})

    body = client.post("/outreach/followups/process").json()
    assert body["cancelled"] == 2
    assert body["sent"] == 0


def test_followup_without_recipient_stays_generated(client: TestClient, db):
    """A lead without any email address: follow-up is generated but not sent."""
    lead = client.post(
        "/leads",
        json={
            "name": "NoMailCo",
            "website": "https://nomailco.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
        },
    )
    lead_id = lead.json()["id"]

    # No sent message exists -> default steps, no recipient anywhere.
    rows = client.post(f"/outreach/leads/{lead_id}/start-followup").json()
    assert len(rows) == 2
    _force_due(client, db, lead_id)

    body = client.post("/outreach/followups/process").json()
    assert body["generated"] == 2
    assert body["sent"] == 0
    assert body["skipped_no_recipient"] >= 1

    followups = client.get(f"/outreach/followups?lead_id={lead_id}").json()
    assert all(f["status"] == "generated" for f in followups)


# ---------------------------------------------------------------------------
# Status transitions / pause-resume
# ---------------------------------------------------------------------------
def test_pause_resume_followup(client: TestClient, db):
    lead_id, _ = _make_sent_draft(client, name="PauseCo")
    fu = client.get(f"/outreach/followups?lead_id={lead_id}").json()[0]

    paused = client.patch(f"/outreach/followups/{fu['id']}", json={"status": "cancelled"}).json()
    assert paused["status"] == "cancelled"
    resumed = client.patch(f"/outreach/followups/{fu['id']}", json={"status": "pending"}).json()
    assert resumed["status"] == "pending"
    assert client.patch(f"/outreach/followups/{fu['id']}", json={"status": "bogus"}).status_code == 422
    assert client.patch("/outreach/followups/999999", json={"status": "pending"}).status_code == 404


def test_followup_status_filter(client: TestClient, db):
    lead_id, _ = _make_sent_draft(client, name="FilterCo")
    pending = client.get("/outreach/followups?status=pending").json()
    assert len(pending) >= 2
    assert all(f["status"] == "pending" for f in pending)
