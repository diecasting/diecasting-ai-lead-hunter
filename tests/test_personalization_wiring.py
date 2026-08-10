"""Phase 14.2.1 — Personalization Pipeline Wiring.

Wires :class:`PersonalizationService` into the campaign outreach-preparation
flow (deterministic / non-AI mode) and verifies:

  * a rank-selected contact gets a personalized subject/body draft
  * a personalization failure falls back to the existing draft path without
    blocking campaign creation
  * the AI path (use_ai=True) is untouched (covered by test_campaign.py)

Offline — no network, no LLM.
"""
import json

from app.campaign import crud as cc_crud, service as svc
from app.models.campaign import CC_STATUS_READY, CC_STATUS_SELECTED
from app.models.contact import Contact
from app.models.email_address import EmailAddress
from app.models.email_draft import EmailDraft
from app.models.lead import CompanyLead
from app.models.manufacturing_capability import ManufacturingCapability


# ---------------------------------------------------------------------------
# Helpers (mirror test_campaign.py)
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


def _seed_contact(db, lead_id, **kw):
    email = kw.pop("email", "john.smith@acme.com")
    addr = EmailAddress(
        company_id=lead_id,
        email=email,
        email_type="personal",
        verification_status=kw.pop("email_status", "valid"),
        verification_score=90,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    contact = Contact(
        lead_id=lead_id,
        full_name=kw.pop("name", "John Smith"),
        first_name=kw.pop("first", "John"),
        email=email,
        title=kw.pop("title", "Purchasing Manager"),
        title_category=kw.pop("category", "procurement"),
        seniority=kw.pop("seniority", "senior"),
        purchasing_score=kw.pop("score", 85),
        priority=kw.pop("priority", "high"),
        email_address_id=addr.id,
        do_not_contact=kw.pop("do_not_contact", False),
        **kw,
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


def _seed_capability(db, **kw):
    defaults = dict(
        process="die casting",
        machine_type="cold chamber",
        tonnage=650,
        material_compatibility="ADC12,A380,AZ91D",
        tolerance_capability="±0.05mm",
        active=True,
    )
    defaults.update(kw)
    cap = ManufacturingCapability(**defaults)
    db.add(cap)
    db.commit()
    db.refresh(cap)
    return cap


def _first_draft(db, camp_id):
    cc = cc_crud.list_contacts(db, camp_id)[0]
    return db.query(EmailDraft).filter(EmailDraft.id == cc.draft_id).first()


# ---------------------------------------------------------------------------
# Wiring tests
# ---------------------------------------------------------------------------
def test_ranked_contact_gets_personalized_draft(client, db):
    lead_id = _make_lead(client)
    _set_lead(
        db, lead_id,
        industry="Die Casting", priority="HIGH",
        materials="ADC12,A380", manufacturing_process="die casting, CNC",
        description="Tier-1 EV component maker",
    )
    _seed_contact(db, lead_id)
    _seed_capability(db, material_compatibility="ADC12,A380")

    camp_id = _make_campaign(
        client, name="Personalized", target_industry="Die Casting",
        daily_limit=100, use_ai=False,
    )
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))
    result = svc.generate_drafts(db, camp_id, use_ai=False)
    assert result["generated"] == 1
    assert result["passed"] == 1

    draft = _first_draft(db, camp_id)
    assert draft is not None
    # Personalization path (not the AI agent) produced the draft.
    assert draft.used_ai is False
    meta = json.loads(draft.research_summary)
    assert meta["source"] == "personalization_service"
    assert draft.personalization_score is not None
    assert draft.personalization_score > 0
    # The ranking engine ran during build_campaign_targets and the
    # personalized body reflects both the company and the ranked contact.
    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    contact = db.query(Contact).filter(Contact.lead_id == lead_id).first()
    assert contact.ranking_score is not None  # rank-selected
    assert lead.name in draft.body
    assert (contact.first_name or contact.full_name) in draft.body
    # Ranking note is embedded because the contact was ranked.
    assert "ranking" in draft.body.lower()


def test_personalization_failure_falls_back_safely(client, db, monkeypatch):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)

    camp_id = _make_campaign(
        client, name="Fallback", target_industry="Die Casting",
        daily_limit=100, use_ai=False,
    )
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))

    # Force the personalization layer to crash; the campaign must still get a
    # draft via the existing AI Sales Agent baseline.
    def _boom(self, company, contact):
        raise RuntimeError("personalization layer exploded")

    monkeypatch.setattr(
        "app.campaign.service.OutreachPersonalizationService.personalize", _boom
    )

    result = svc.generate_drafts(db, camp_id, use_ai=False)
    assert result["generated"] == 1
    assert result["passed"] == 1

    draft = _first_draft(db, camp_id)
    assert draft is not None
    # Fallback draft is the agent's deterministic baseline (no AI, no
    # personalization_service marker).
    assert draft.used_ai is False
    meta = json.loads(draft.research_summary)
    assert meta.get("source") != "personalization_service"


def test_ai_path_unchanged_uses_agent(client, db, monkeypatch):
    # Regression: the AI path must still route through the AI Sales Agent
    # (complete_json), not the deterministic personalization layer.
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", priority="HIGH")
    _seed_contact(db, lead_id)
    camp_id = _make_campaign(
        client, name="AI", target_industry="Die Casting",
        daily_limit=100, use_ai=True,
    )
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))

    monkeypatch.setattr(
        "app.ai_sales_agent.personalization.complete_json",
        lambda system, user, **kw: {
            "subject": "AI: Precision die casting partnership",
            "opening": "Hi there,",
            "body": "AI generated body about die casting tolerances.",
            "call_to_action": "Lets schedule a short technical call.",
        },
    )
    result = svc.generate_drafts(db, camp_id, use_ai=True)
    assert result["generated"] == 1
    draft = _first_draft(db, camp_id)
    assert draft.used_ai is True
    assert draft.subject.startswith("AI:")
