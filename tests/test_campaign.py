"""Phase 9.5 — AI Outreach Campaign Engine.

Covers the additive campaign layer that orchestrates targeting, batch draft
generation (reusing the AI Sales Agent + Outreach baseline), queue management
and analytics on top of the existing CompanyLead / Contact / EmailAddress /
EmailDraft infrastructure.

Design notes
------------
  * All AI generation goes through ``app.ai_sales_agent.service`` (which itself
    reuses the Outreach Engine's deterministic baseline) — never duplicated.
  * The campaign engine never calls the outreach send path, so a regression test
    asserts that building targets / generating drafts never creates an
    ``outreach_messages`` row.
  * The AI-enhancement path is exercised by monkeypatching the *imported*
    ``complete_json`` name in ``personalization`` (modules bind the symbol at
    import time).
  * No network / LLM is touched — ``complete_json`` degrades to the template
    path when no provider is configured.
"""
from datetime import datetime, timezone

from app.campaign import crud as cc_crud, service as svc
from app.models.campaign import (
    CC_STATUS_QUEUED,
    CC_STATUS_READY,
    CC_STATUS_REJECTED,
    CC_STATUS_REPLIED,
    CC_STATUS_RFQ,
    CC_STATUS_SELECTED,
    CC_STATUS_SENT,
    Campaign,
    CampaignContact,
)
from app.models.contact import Contact
from app.models.email_address import EmailAddress
from app.models.email_draft import EmailDraft
from app.models.lead import CompanyLead
from app.models.outreach_message import OutreachMessage


# ---------------------------------------------------------------------------
# Helpers (mirror test_ai_sales_agent.py)
# ---------------------------------------------------------------------------
def _make_lead(client, website="https://acme.com"):
    r = client.post("/leads", json={"name": "Acme Castings", "website": website})
    assert r.status_code == 201
    return r.json()["id"]


def _set_lead(db, lead_id, **kw):
    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    assert lead is not None
    for k, v in kw.items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead


def _seed_contact(
    db,
    lead_id,
    *,
    name="John Smith",
    first="John",
    email="john.smith@acme.com",
    title="Purchasing Manager",
    category="procurement",
    score=85,
    priority="high",
    seniority="senior",
    email_status="valid",
    do_not_contact=False,
):
    addr = EmailAddress(
        company_id=lead_id,
        email=email,
        email_type="personal",
        verification_status=email_status,
        verification_score=90,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    contact = Contact(
        lead_id=lead_id,
        full_name=name,
        first_name=first,
        email=email,
        title=title,
        title_category=category,
        seniority=seniority,
        purchasing_score=score,
        priority=priority,
        email_address_id=addr.id,
        do_not_contact=do_not_contact,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _make_campaign(client, **kw):
    body = {"name": kw.pop("name", "Spring Push")}
    body.update(kw)
    r = client.post("/api/campaign", json=body)
    assert r.status_code == 200
    return r.json()["id"]


def _fake_complete_json(system, user, **kw):
    return {
        "subject": "AI: Precision die casting partnership",
        "opening": "Hi there,",
        "body": "AI generated body about die casting tolerances.",
        "call_to_action": "Lets schedule a short technical call.",
    }


# ---------------------------------------------------------------------------
# Campaign CRUD (direct)
# ---------------------------------------------------------------------------
def test_campaign_crud_direct(db):
    camp = svc.create_campaign(db, name="Q3 Blast", daily_limit=25)
    assert camp.id is not None
    assert camp.name == "Q3 Blast"
    assert camp.daily_limit == 25

    fetched = svc.get_campaign(db, camp.id)
    assert fetched is not None

    assert len(svc.list_campaigns(db)) >= 1

    updated = svc.update_campaign(db, camp.id, status="active", daily_limit=10)
    assert updated.status == "active"
    assert updated.daily_limit == 10

    assert svc.delete_campaign(db, camp.id) is True
    assert svc.get_campaign(db, camp.id) is None


# ---------------------------------------------------------------------------
# Campaign CRUD (API) + 404 / 422
# ---------------------------------------------------------------------------
def test_api_campaign_lifecycle(client, db):
    camp_id = _make_campaign(client, name="API Campaign", daily_limit=15)
    assert camp_id is not None

    lst = client.get("/api/campaign")
    assert lst.status_code == 200
    assert any(c["id"] == camp_id for c in lst.json())

    get_r = client.get(f"/api/campaign/{camp_id}")
    assert get_r.status_code == 200
    assert get_r.json()["name"] == "API Campaign"

    upd = client.put(f"/api/campaign/{camp_id}", json={"status": "active"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "active"

    dele = client.delete(f"/api/campaign/{camp_id}")
    assert dele.status_code == 200
    assert client.get(f"/api/campaign/{camp_id}").status_code == 404
    assert client.put(f"/api/campaign/{camp_id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/campaign/{camp_id}").status_code == 404


# ---------------------------------------------------------------------------
# Selector — target company filtering
# ---------------------------------------------------------------------------
def test_select_targets_filters(client, db):
    inc = _make_lead(client, website="https://inc.com")
    _set_lead(db, inc, industry="Die Casting", country="Germany",
              priority="HIGH", sales_priority="HIGH", lead_score=90)
    exc_ind = _make_lead(client, website="https://other.com")
    _set_lead(db, exc_ind, industry="Plastics", country="Germany",
              priority="HIGH", sales_priority="HIGH")
    dnc = _make_lead(client, website="https://dnc.com")
    _set_lead(db, dnc, industry="Die Casting", country="Germany",
              do_not_contact=True)

    # Industry + country filter only.
    hits = svc.select_targets(db, target_industry="Die Casting",
                               target_country="Germany")
    ids = {c.id for c in hits}
    assert inc in ids
    assert exc_ind not in ids
    assert dnc not in ids  # excluded by do_not_contact

    # Priority gate excludes MEDIUM/LOW.
    low = _make_lead(client, website="https://low.com")
    _set_lead(db, low, industry="Die Casting", country="Germany",
              priority="LOW", sales_priority="LOW")
    hits2 = svc.select_targets(db, target_industry="Die Casting",
                               target_country="Germany", min_priority="HIGH")
    ids2 = {c.id for c in hits2}
    assert inc in ids2
    assert low not in ids2


# ---------------------------------------------------------------------------
# Selector — contact selection + ranking + deliverability
# ---------------------------------------------------------------------------
def test_select_contacts_ranking_and_deliverability(client, db):
    lead_id = _make_lead(client)
    # procurement, high score — should rank first
    _seed_contact(db, lead_id, name="Sam Buyer", email="sam@acme.com",
                  title="Purchasing Manager", category="procurement", score=90)
    # engineering, lower score
    _seed_contact(db, lead_id, name="Eve Eng", email="eve@acme.com",
                  title="Quality Engineer", category="engineering", score=60)
    # invalid e-mail -> excluded
    _seed_contact(db, lead_id, name="Bad Addr", email="bad@acme.com",
                  title="Buyer", category="procurement", score=80,
                  email_status="invalid")
    # do_not_contact -> excluded
    _seed_contact(db, lead_id, name="No Mail", email="no@acme.com",
                  title="Buyer", category="procurement", score=80,
                  do_not_contact=True)

    ranked = svc.select_contacts(db, lead_id)
    emails = [c.email for c in ranked]
    assert emails[0] == "sam@acme.com"           # procurement first
    assert "eve@acme.com" in emails
    assert "bad@acme.com" not in emails           # invalid excluded
    assert "no@acme.com" not in emails            # DNC excluded


# ---------------------------------------------------------------------------
# Selector — duplicate prevention (across + within company)
# ---------------------------------------------------------------------------
def test_build_targets_dedup(client, db):
    a = _make_lead(client, website="https://a.com")
    b = _make_lead(client, website="https://b.com")
    _set_lead(db, a, industry="Die Casting", country="DE", priority="HIGH")
    _set_lead(db, b, industry="Die Casting", country="DE", priority="HIGH")

    # One shared e-mail reused across both companies AND twice within company A
    # (reusing the same EmailAddress row so the (company_id, email) unique
    # constraint is honoured). Only ONE campaign entry should result.
    ea_a = EmailAddress(company_id=a, email="shared@acme.com",
                        email_type="personal", verification_status="valid")
    ea_b = EmailAddress(company_id=b, email="shared@acme.com",
                        email_type="personal", verification_status="valid")
    db.add_all([ea_a, ea_b])
    db.commit()
    db.refresh(ea_a)
    db.refresh(ea_b)
    for name, lead_id, addr in (
        ("Shared A", a, ea_a.id), ("Shared A2", a, ea_a.id),
        ("Shared B", b, ea_b.id),
    ):
        db.add(Contact(
            lead_id=lead_id, full_name=name, first_name="Shared",
            email="shared@acme.com", title="Buyer", title_category="procurement",
            seniority="senior", purchasing_score=80, priority="high",
            email_address_id=addr,
        ))
    db.commit()

    camp_id = _make_campaign(client, name="Dedup", target_industry="Die Casting",
                             target_country="DE", min_priority="HIGH",
                             daily_limit=100)
    added = svc.build_campaign_targets(
        db, svc.get_campaign(db, camp_id), max_per_company=5
    )
    # Only ONE entry total despite 3 contact rows sharing one e-mail.
    assert added == 1
    rows = cc_crud.list_contacts(db, camp_id)
    assert len(rows) == 1
    assert rows[0].to_email == "shared@acme.com"


# ---------------------------------------------------------------------------
# Batch generation (deterministic) + regression guard
# ---------------------------------------------------------------------------
def test_generate_drafts_deterministic(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)

    camp_id = _make_campaign(client, name="Gen", target_industry="Die Casting",
                             daily_limit=100, use_ai=False)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))

    before = db.query(OutreachMessage).count()
    result = svc.generate_drafts(db, camp_id, use_ai=False, tone="professional")
    assert result["generated"] == 1
    assert result["passed"] == 1
    assert result["rejected"] == 0

    rows = cc_crud.list_contacts(db, camp_id)
    assert rows[0].status == CC_STATUS_READY
    assert rows[0].draft_id is not None
    assert rows[0].quality_score is not None
    # A draft row exists for the campaign contact.
    assert db.query(EmailDraft).filter(
        EmailDraft.id == rows[0].draft_id).count() == 1
    # Regression: campaign generation must NOT create outreach messages.
    assert db.query(OutreachMessage).count() == before


def test_generate_drafts_ai_merge(client, db, monkeypatch):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)
    camp_id = _make_campaign(client, name="GenAI", target_industry="Die Casting",
                             daily_limit=100, use_ai=True)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))

    monkeypatch.setattr(
        "app.ai_sales_agent.personalization.complete_json", _fake_complete_json
    )
    result = svc.generate_drafts(db, camp_id, use_ai=True)
    assert result["generated"] == 1
    draft = db.query(EmailDraft).filter(
        EmailDraft.id == cc_crud.list_contacts(db, camp_id)[0].draft_id
    ).first()
    assert draft.used_ai is True
    assert draft.subject.startswith("AI:")


def test_quality_gate_rejects_low_scoring(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)
    # Gate of 999 is impossible to satisfy -> every draft rejected.
    camp_id = _make_campaign(client, name="Gate", target_industry="Die Casting",
                             daily_limit=100, quality_gate_min=999)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))
    result = svc.generate_drafts(db, camp_id, use_ai=False)
    assert result["generated"] == 1
    assert result["passed"] == 0
    assert result["rejected"] == 1
    rows = cc_crud.list_contacts(db, camp_id)
    assert rows[0].status == CC_STATUS_REJECTED


# ---------------------------------------------------------------------------
# Queue management — daily sending limit
# ---------------------------------------------------------------------------
def test_queue_respects_daily_limit(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    # Three deliverable contacts -> three ready drafts.
    for i in range(3):
        _seed_contact(db, lead_id, name=f"C{i}", email=f"c{i}@acme.com",
                      title="Buyer", category="procurement", score=80)
    camp_id = _make_campaign(client, name="Queue", target_industry="Die Casting",
                             daily_limit=2)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))
    svc.generate_drafts(db, camp_id, use_ai=False)

    as_of = datetime.now(timezone.utc)
    queued = svc.queue_ready_contacts(db, camp_id, as_of=as_of, daily_limit=2)
    assert queued == 2
    rows = cc_crud.list_contacts(db, camp_id)
    assert sum(1 for r in rows if r.status == CC_STATUS_QUEUED) == 2
    # Second pass: daily cap already reached -> nothing more queued.
    queued2 = svc.queue_ready_contacts(db, camp_id, as_of=as_of, daily_limit=2)
    assert queued2 == 0


# ---------------------------------------------------------------------------
# Analytics — sent / reply / RFQ / conversion
# ---------------------------------------------------------------------------
def test_campaign_stats_counts(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    for i in range(4):
        _seed_contact(db, lead_id, name=f"S{i}", email=f"s{i}@acme.com",
                      title="Buyer", category="procurement", score=80)
    camp_id = _make_campaign(client, name="Stats", target_industry="Die Casting",
                             daily_limit=100)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))
    svc.generate_drafts(db, camp_id, use_ai=False)

    rows = cc_crud.list_contacts(db, camp_id)
    as_of = datetime.now(timezone.utc)
    # 2 sent, 1 of those replied, 1 became an RFQ (also counts as sent+replied).
    svc.mark_sent(db, rows[0].id, as_of=as_of)
    svc.mark_sent(db, rows[1].id, as_of=as_of)
    svc.mark_replied(db, rows[1].id, as_of=as_of)
    svc.mark_rfq(db, rows[2].id, as_of=as_of)

    stats = svc.campaign_stats(db, camp_id)
    assert stats["sent"] == 3          # rows 0,1,2 (rfq implies sent)
    assert stats["replied"] == 2       # rows 1,2
    assert stats["rfq"] == 1           # row 2
    assert stats["conversion"] == round(1 / 3, 4)

    # Cached counters on the campaign row stay in sync.
    camp = svc.get_campaign(db, camp_id)
    assert camp.sent_count == 3
    assert camp.reply_count == 2
    assert camp.rfq_count == 1


# ---------------------------------------------------------------------------
# API — targets / generate / queue / stats / outcomes
# ---------------------------------------------------------------------------
def test_api_build_and_generate_and_stats(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)
    camp_id = _make_campaign(client, name="API Flow", target_industry="Die Casting",
                             daily_limit=100, use_ai=False)

    t = client.post(f"/api/campaign/{camp_id}/targets", json={"max_per_company": 3})
    assert t.status_code == 200
    assert t.json()["added"] == 1
    assert t.json()["total_targets"] == 1

    g = client.post(f"/api/campaign/{camp_id}/generate", json={"use_ai": False})
    assert g.status_code == 200
    assert g.json()["passed"] == 1

    s = client.get(f"/api/campaign/{camp_id}/stats")
    assert s.status_code == 200
    assert s.json()["total_targets"] == 1
    assert s.json()["by_status"].get(CC_STATUS_READY, 0) == 1

    q = client.post(f"/api/campaign/{camp_id}/queue", json={"daily_limit": 100})
    assert q.status_code == 200
    assert q.json()["queued"] == 1

    contacts = client.get(f"/api/campaign/{camp_id}/contacts").json()
    cc_id = contacts[0]["id"]
    sent = client.post(f"/api/campaign/{camp_id}/contact/{cc_id}/sent")
    assert sent.status_code == 200
    assert sent.json()["status"] == CC_STATUS_SENT

    stats2 = client.get(f"/api/campaign/{camp_id}/stats").json()
    assert stats2["sent"] == 1


def test_api_invalid_contact_status_422(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)
    camp_id = _make_campaign(client, name="Invalid", target_industry="Die Casting",
                             daily_limit=100)
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))
    cc_id = cc_crud.list_contacts(db, camp_id)[0].id
    r = client.put(f"/api/campaign/{camp_id}/contact/{cc_id}",
                   json={"status": "nonsense"})
    assert r.status_code == 422


def test_api_campaign_404(client):
    assert client.get("/api/campaign/999999").status_code == 404
    assert client.post("/api/campaign/999999/targets",
                       json={}).status_code == 404
    assert client.get("/api/campaign/999999/stats").status_code == 404
    assert client.post("/api/campaign/999999/generate",
                       json={}).status_code == 404
