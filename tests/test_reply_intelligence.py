"""Phase 10: Reply Intelligence Sales Automation tests.

Covers:
  * the three new classifier intents (wrong_contact / not_now / spam),
  * the extended action engine — SalesTask creation, RFQ extraction, and
    CampaignContact status sync,
  * the new ``/api/reply`` surfaces (analyze, rfq-queue, sales-tasks CRUD,
    replies listing).

All tests are offline: there is no real IMAP, no real LLM (the deterministic
extractor is the source of truth and ``complete_json`` is not exercised here).
"""
from datetime import datetime, timezone

from app.campaign import crud as campaign_crud
from app.models.campaign import CampaignContact
from app.models.lead import CompanyLead
from app.models.reply_rfq_extraction import ReplyRFQExtraction
from app.models.sales_task import SalesTask
from app.outreach.reply_ai import analyzer as reply_analyzer
from app.outreach.reply_ai.classifier import INTENTS, classify_reply


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_lead_unique(client, db, name, email):
    """Create a lead with a *unique* contact_email so inbox matching is exact."""
    r = client.post(
        "/leads",
        json={
            "name": name,
            "website": f"https://{name.lower()}.example.com",
            "contact_email": email,
        },
    )
    assert r.status_code == 201
    lid = r.json()["id"]
    # ensure the persisted contact_email matches what the matcher will see
    lead = db.query(CompanyLead).filter(CompanyLead.id == lid).first()
    lead.contact_email = email
    db.add(lead)
    db.commit()
    return lid


# ---------------------------------------------------------------------------
# Classifier (new intents)
# ---------------------------------------------------------------------------
def test_classify_wrong_contact():
    r = classify_reply(
        "You have the wrong person, please contact our purchasing manager instead."
    )
    assert r.intent == "wrong_contact"


def test_classify_not_now():
    r = classify_reply("Not now, we have no budget this quarter, maybe later.")
    assert r.intent == "not_now"


def test_classify_spam():
    r = classify_reply(
        "Congratulations you are a winner, claim your prize now, free gift!"
    )
    assert r.intent == "spam"


def test_new_intents_present():
    assert {"wrong_contact", "not_now", "spam"}.issubset(set(INTENTS))


# ---------------------------------------------------------------------------
# Extended action engine (via the analyzer pipeline)
# ---------------------------------------------------------------------------
def test_rfq_creates_task_extraction_and_campaign_sync(client, db):
    lid = _make_lead_unique(client, db, "RfqSync", "rfqsync@example.com")

    camp = campaign_crud.create_campaign(db, name="Phase10Camp")
    cc = campaign_crud.add_contact(
        db, campaign_id=camp.id, company_id=lid, status="sent"
    )

    lead = db.query(CompanyLead).filter(CompanyLead.id == lid).first()
    analysis, actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text=(
            "Please send us a quote for 5000 pcs ADC12 die cast housing, ASAP."
        ),
    )
    assert analysis.intent == "rfq_request"
    assert any(a.startswith("sales_task created") for a in actions)
    assert any("rfq_extraction created" in a for a in actions)
    assert any("campaign_contacts -> rfq: 1" in a for a in actions)

    tasks = db.query(SalesTask).filter(SalesTask.reply_id == analysis.id).all()
    assert len(tasks) == 1
    assert tasks[0].category == "rfq"
    assert tasks[0].company_id == lid

    ext = (
        db.query(ReplyRFQExtraction)
        .filter(ReplyRFQExtraction.analysis_id == analysis.id)
        .first()
    )
    assert ext is not None
    assert ext.material == "ADC12"
    assert ext.quantity is not None  # "5000 pcs"
    assert ext.used_ai is False  # deterministic fallback (no LLM in tests)

    db.expire_all()
    cc2 = db.query(CampaignContact).filter(CampaignContact.id == cc.id).first()
    assert cc2.status == "rfq"
    camp2 = campaign_crud.get_campaign(db, camp.id)
    assert camp2.rfq_count == 1


def test_interested_creates_sales_task_and_synced_reply(client, db):
    lid = _make_lead_unique(client, db, "IntSync", "intsync@example.com")
    camp = campaign_crud.create_campaign(db, name="Phase10Camp2")
    cc = campaign_crud.add_contact(
        db, campaign_id=camp.id, company_id=lid, status="sent"
    )

    lead = db.query(CompanyLead).filter(CompanyLead.id == lid).first()
    analysis, actions = reply_analyzer.analyze_reply(
        db, lead, reply_text="We are very interested, please schedule a call."
    )
    assert analysis.intent == "interested"
    assert any(a.startswith("sales_task created") for a in actions)
    assert any("campaign_contacts -> replied: 1" in a for a in actions)

    db.expire_all()
    cc2 = db.query(CampaignContact).filter(CampaignContact.id == cc.id).first()
    assert cc2.status == "replied"


def test_unknown_still_has_no_actions(client, db):
    lid = _make_lead_unique(client, db, "UnkSync", "unksync@example.com")
    lead = db.query(CompanyLead).filter(CompanyLead.id == lid).first()
    analysis, actions = reply_analyzer.analyze_reply(
        db, lead, reply_text="Thanks."
    )
    assert analysis.intent == "unknown"
    assert actions == []  # preserves the Phase 6 API contract


# ---------------------------------------------------------------------------
# API: /api/reply/analyze
# ---------------------------------------------------------------------------
def test_api_analyze_creates_task_and_extraction(client, db):
    lid = _make_lead_unique(client, db, "ApiRfq", "apirfq@example.com")
    r = client.post(
        "/api/reply/analyze",
        json={
            "sender_email": "apirfq@example.com",
            "subject": "Re: quote",
            "body": (
                "Please send us a quote for 2000 pieces ADC12 die casting, "
                "deadline end of quarter."
            ),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "rfq_request"
    assert body["lead_id"] == lid
    assert len(body["sales_task_ids"]) == 1
    assert body["rfq_extraction_id"] is not None

    queue = client.get("/api/reply/rfq-queue").json()
    assert any(
        item["extraction_id"] == body["rfq_extraction_id"] for item in queue
    )


def test_api_analyze_no_matching_lead(client):
    r = client.post(
        "/api/reply/analyze",
        json={"sender_email": "nobody@nowhere.example", "body": "hello there"},
    )
    assert r.status_code == 404


def test_api_analyze_requires_body(client):
    r = client.post("/api/reply/analyze", json={"sender_email": "a@b.com"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# API: /api/reply/sales-tasks CRUD
# ---------------------------------------------------------------------------
def test_sales_tasks_crud(client):
    r = client.post(
        "/api/reply/sales-tasks",
        json={"title": "Call prospect", "priority": "high", "category": "sales"},
    )
    assert r.status_code == 200
    tid = r.json()["id"]

    listing = client.get("/api/reply/sales-tasks").json()
    assert any(t["id"] == tid for t in listing)

    r2 = client.put(f"/api/reply/sales-tasks/{tid}", json={"status": "done"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "done"

    r3 = client.put(f"/api/reply/sales-tasks/{tid}", json={"priority": "urgent"})
    assert r3.status_code == 422

    assert client.get("/api/reply/sales-tasks/999999").status_code == 404


def test_sales_tasks_filter_by_status(client):
    client.post(
        "/api/reply/sales-tasks",
        json={"title": "Open task", "priority": "low", "category": "review"},
    )
    listing = client.get("/api/reply/sales-tasks", params={"status": "done"}).json()
    assert all(t["status"] == "done" for t in listing)


# ---------------------------------------------------------------------------
# API: /api/reply/replies listing
# ---------------------------------------------------------------------------
def test_list_replies(client, db):
    from app.models.incoming_email import IncomingEmail

    em = IncomingEmail(
        sender_email="x@y.example",
        subject="hi",
        body="hello",
        received_at=datetime.now(timezone.utc),
        processed=False,
    )
    db.add(em)
    db.commit()

    rows = client.get("/api/reply/replies").json()
    assert any(r["sender_email"] == "x@y.example" for r in rows)

    filtered = client.get("/api/reply/replies", params={"processed": "true"}).json()
    assert all(r["processed"] is True for r in filtered)
