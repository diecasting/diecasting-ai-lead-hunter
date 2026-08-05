"""Phase 6 Stage 2: AI Reply Intelligence tests.

Covers intent classification (all 8 categories), the intent-driven CRM
automation (status transitions, follow-up cancellation), API validation, and
the reply-analysis listing endpoint.
"""
from app.models.followup import OutreachFollowUp
from app.outreach.followup import scheduler as followup_scheduler
from app.outreach.reply_ai.classifier import INTENTS, classify_reply


# ---------------------------------------------------------------------------
# Classifier (unit)
# ---------------------------------------------------------------------------
def test_classify_out_of_office():
    r = classify_reply("I am out of office until Monday and will be back next week.")
    assert r.intent == "out_of_office"
    assert 0 <= r.confidence <= 100


def test_classify_not_interested():
    r = classify_reply("Not interested, please stop sending and take me off your list.")
    assert r.intent == "not_interested"


def test_classify_supplier_existing():
    r = classify_reply("We already have a supplier for this and are happy with our supplier.")
    assert r.intent == "supplier_existing"


def test_classify_price_request():
    r = classify_reply("Could you send me your price list and unit price for ADC12 housings?")
    assert r.intent == "price_request"


def test_classify_rfq_request():
    r = classify_reply("Please send us a quote, we have an open RFQ for die cast housings.")
    assert r.intent == "rfq_request"


def test_classify_technical_question():
    r = classify_reply("What tolerances and surface finish can you hold? Do you have ISO 9001?")
    assert r.intent == "technical_question"


def test_classify_interested():
    r = classify_reply("We are very interested. Please schedule a call to discuss more.")
    assert r.intent == "interested"


def test_classify_unknown():
    r = classify_reply("Thanks.")
    assert r.intent == "unknown"


def test_classify_confidence_deterministic_and_bounded():
    a = classify_reply("very interested, please schedule a call with us")
    b = classify_reply("very interested, please schedule a call with us")
    assert a.confidence == b.confidence
    assert 0 <= a.confidence <= 100


def test_intent_categories():
    assert set(INTENTS) == {
        "interested",
        "rfq_request",
        "technical_question",
        "price_request",
        "supplier_existing",
        "not_interested",
        "out_of_office",
        "unknown",
    }


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _make_lead(client, name="ReplyCo"):
    r = client.post(
        "/leads",
        json={
            "name": name,
            "website": f"https://{name.lower()}.example.com",
            "contact_email": "buyer@reply.example.com",
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def _schedule_followups(client, db, lead_id):
    from app.models.lead import CompanyLead

    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    rows = followup_scheduler.schedule_for_lead(db, lead)
    db.refresh(lead)
    return rows


# ---------------------------------------------------------------------------
# CRM automation via API
# ---------------------------------------------------------------------------
def test_api_rfq_request_updates_status(client):
    lid = _make_lead(client, "RfqCo")
    r = client.post(
        "/outreach/replies/analyze",
        json={
            "lead_id": lid,
            "reply_text": "Please send us a quote, we have an open RFQ for die cast housings.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "rfq_request"
    assert "lead_status -> rfq" in body["applied_actions"]
    # new -> rfq is not in the strict state machine; the automation forces it.
    assert client.get(f"/leads/{lid}").json()["lead_status"] == "rfq"
    # timeline records the reply milestone
    tl = client.get(f"/leads/{lid}/timeline").json()
    assert any(e["event_type"] == "replied" for e in tl["events"])


def test_api_interested_updates_status(client):
    lid = _make_lead(client, "IntCo")
    r = client.post(
        "/outreach/replies/analyze",
        json={
            "lead_id": lid,
            "reply_text": "We are very interested. Please schedule a call.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "interested"
    assert "lead_status -> qualified" in body["applied_actions"]
    assert client.get(f"/leads/{lid}").json()["lead_status"] == "qualified"


def test_api_not_interested_cancels_followups(client, db):
    lid = _make_lead(client, "NoIntCo")
    rows = _schedule_followups(client, db, lid)
    assert len(rows) == 2 and all(r.status == "pending" for r in rows)

    r = client.post(
        "/outreach/replies/analyze",
        json={"lead_id": lid, "reply_text": "Not interested, please stop sending."},
    )
    assert r.status_code == 200
    assert r.json()["intent"] == "not_interested"
    assert any("follow-ups cancelled" in a for a in r.json()["applied_actions"])

    # The API request ran in its own session — expire the fixture session's
    # identity map so the follow-up rows are re-read from the DB.
    db.expire_all()
    fus = db.query(OutreachFollowUp).filter(OutreachFollowUp.lead_id == lid).all()
    assert all(f.status == "cancelled" for f in fus)
    assert client.get(f"/leads/{lid}").json()["do_not_contact"] is True


def test_api_supplier_existing_stops_sequence(client, db):
    lid = _make_lead(client, "SupCo")
    _schedule_followups(client, db, lid)

    r = client.post(
        "/outreach/replies/analyze",
        json={"lead_id": lid, "reply_text": "We already have a supplier for this."},
    )
    assert r.status_code == 200
    assert r.json()["intent"] == "supplier_existing"
    assert any("sequence stopped" in a for a in r.json()["applied_actions"])

    db.expire_all()
    fus = db.query(OutreachFollowUp).filter(OutreachFollowUp.lead_id == lid).all()
    assert all(f.status == "cancelled" for f in fus)


# ---------------------------------------------------------------------------
# API validation + listing
# ---------------------------------------------------------------------------
def test_api_validation(client):
    lid = _make_lead(client, "ValCo")

    # empty reply_text -> 422
    r = client.post("/outreach/replies/analyze", json={"lead_id": lid, "reply_text": ""})
    assert r.status_code == 422

    # unknown lead -> 404
    r = client.post(
        "/outreach/replies/analyze", json={"lead_id": 999999, "reply_text": "hello"}
    )
    assert r.status_code == 404

    # message belonging to another lead -> 404
    lid2 = _make_lead(client, "OtherCo")
    m = client.post(f"/leads/{lid2}/generate-email")
    assert m.status_code == 201
    mid = m.json()["id"]
    r = client.post(
        "/outreach/replies/analyze",
        json={"lead_id": lid, "message_id": mid, "reply_text": "hi there"},
    )
    assert r.status_code == 404


def test_api_list_reply_analyses(client):
    lid = _make_lead(client, "ListCo")
    client.post(
        "/outreach/replies/analyze",
        json={
            "lead_id": lid,
            "reply_text": "We are very interested, please schedule a call.",
        },
    )
    client.post(
        "/outreach/replies/analyze",
        json={"lead_id": lid, "reply_text": "Thanks."},
    )

    rows = client.get(f"/outreach/leads/{lid}/reply-analysis").json()
    assert len(rows) == 2
    assert rows[0]["intent"] == "unknown"  # newest first
    assert rows[0]["applied_actions"] == []
    assert rows[1]["intent"] == "interested"

    assert client.get("/outreach/leads/999999/reply-analysis").status_code == 404
