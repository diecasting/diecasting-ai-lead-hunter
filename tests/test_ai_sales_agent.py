"""Phase 9 — AI Sales Agent.

Covers the additive AI Sales Agent layer that sits on top of the existing
Outreach Engine / Contact Intelligence / Email Discovery infrastructure:

  * role-based sales prompts          -- ``app.ai_sales_agent.prompts``
  * deterministic email quality score -- ``app.ai_sales_agent.quality``
  * company research brief generator  -- ``app.ai_sales_agent.research``
  * AI personalization engine         -- ``app.ai_sales_agent.personalization``
  * draft management (CRUD)           -- ``app.ai_sales_agent.crud``
  * orchestration service             -- ``app.ai_sales_agent.service``
  * API endpoints                     -- ``app.api.agent``

Design notes for the tests
---------------------------
  * All AI calls go through ``complete_json``, which degrades to the
    deterministic template path when no provider is configured. The test suite
    therefore never touches the network: the AI-enhancement path is exercised by
    monkeypatching the *imported* ``complete_json`` name in the consumer module
    (``personalization`` / ``research``) -- not the source module, because those
    modules bind the symbol at import time.
  * The Outreach Engine's deterministic ``generate_email_from_lead`` is reused
    read-only and the send path is never invoked, so a regression test asserts
    that generating / scoring a draft never creates an ``outreach_messages`` row.
"""
import json

from app.ai_sales_agent import (
    crud as draft_crud,
    personalization,
    prompts,
    quality,
    research as research_gen,
    service as svc,
)
from app.ai_sales_agent.prompts import available_categories, role_cta, role_focus, role_prompt
from app.models.contact import Contact
from app.models.email_address import EmailAddress
from app.models.email_draft import DRAFT_STATUS_DRAFT, EmailDraft
from app.models.lead import CompanyLead
from app.models.outreach_message import OutreachMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_lead(client, website="https://acme.com", contact_email=None,
               contact_name=None, contact_role=None):
    body = {"name": "Acme Castings", "website": website}
    if contact_email:
        body["contact_email"] = contact_email
    if contact_name:
        body["contact_name"] = contact_name
    if contact_role:
        body["contact_role"] = contact_role
    r = client.post("/leads", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def _load_lead(db, lead_id):
    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    assert lead is not None
    return lead


def _set_lead_scores(db, lead_id, **kw):
    lead = _load_lead(db, lead_id)
    for k, v in kw.items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead


def _seed_contact(db, lead_id, *, name="John Smith", first="John",
                  email="john.smith@acme.com", title="Purchasing Manager",
                  category="procurement", score=85, priority="high",
                  email_status="valid"):
    email_addr = EmailAddress(
        company_id=lead_id,
        email=email,
        email_type="personal",
        verification_status=email_status,
        verification_score=90,
    )
    db.add(email_addr)
    db.commit()
    db.refresh(email_addr)
    contact = Contact(
        lead_id=lead_id,
        full_name=name,
        first_name=first,
        email=email,
        title=title,
        title_category=category,
        purchasing_score=score,
        priority=priority,
        email_address_id=email_addr.id,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _fake_complete_json(system, user, **kw):
    """Stand-in for the LLM that returns a recognisable AI rewrite."""
    return {
        "subject": "AI: Precision die casting partnership for Acme Castings",
        "opening": "Hi John,",
        "body": "AI generated body about high pressure die casting tolerances.",
        "call_to_action": "Lets schedule a short technical call.",
    }


# ---------------------------------------------------------------------------
# Role-based sales prompts
# ---------------------------------------------------------------------------
def test_available_categories_exhaustive():
    cats = available_categories()
    for expected in (
        "procurement", "engineering", "executive",
        "operations", "sales", "finance", "other",
    ):
        assert expected in cats


def test_role_prompt_focus_and_cta():
    # Each persona has a system prompt + a focus string + a CTA theme.
    assert role_prompt("procurement")
    assert "cost" in role_focus("procurement").lower()
    assert role_cta("procurement")
    # Engineering focuses on tolerances / DFM.
    assert "tolerance" in role_focus("engineering").lower()
    # Unknown categories fall back to "other" without raising.
    assert role_prompt("does-not-exist")
    assert role_focus("does-not-exist")
    assert role_cta("does-not-exist")


# ---------------------------------------------------------------------------
# Email quality scoring (deterministic)
# ---------------------------------------------------------------------------
def test_quality_scoring_good_email():
    subject = "Precision die casting partnership for Acme Castings"
    opening = "Dear John,"
    body = (
        "John, I hope this finds you well. Acme Castings is expanding its "
        "aluminum die casting program and we would like to schedule a "
        "technical review of your high pressure die casting needs. Could we "
        "explore how our tolerances and lead times fit your roadmap? "
        "Best regards,"
    )
    cta = "Schedule a 20 minute call with our engineering team."
    score = quality.score_email(subject, "\n\n".join([opening, body, cta]),
                                company="Acme Castings", to_name="John Smith")
    assert score.overall >= 80
    # A well-formed email should surface few (if any) suggestions.
    assert len(score.suggestions) <= 2
    assert score.personalization == 100
    assert score.cta == 100
    assert score.structure == 100


def test_quality_scoring_poor_email():
    score = quality.score_email(
        "", "Buy now! Free guarantee! Click here!!!",
        company="Acme Castings", to_name="John Smith",
    )
    assert score.overall < 60
    assert score.personalization == 0
    assert score.suggestions  # should flag missing subject / personalization etc.
    assert any("spam" in s.lower() or "hype" in s.lower() for s in score.suggestions)


def test_quality_scoring_is_deterministic():
    subject = "Subject here"
    body = ("Body text that is reasonably long and references Acme Castings "
            "and says hello John. Best regards")
    a = quality.score_email(subject, body, company="Acme Castings", to_name="John")
    b = quality.score_email(subject, body, company="Acme Castings", to_name="John")
    assert a.overall == b.overall
    assert a.to_dict() == b.to_dict()


def test_quality_score_to_dict_shape():
    score = quality.score_email("Hello", "World best regards")
    d = score.to_dict()
    assert set(d.keys()) == {"overall", "dimensions", "suggestions"}
    assert set(d["dimensions"].keys()) == {
        "length", "personalization", "cta", "readability",
        "professionalism", "structure",
    }


# ---------------------------------------------------------------------------
# Company research brief generator
# ---------------------------------------------------------------------------
def _fake_lead(lead_id, priority="LOW", **kw):
    attrs = {
        "id": lead_id, "name": "Acme Castings", "industry": "", "country": "",
        "business_type": "", "materials": "", "manufacturing_process": "",
        "description": "", "buying_signal": "", "sales_priority": priority,
        "casting_need_score": 10, "cnc_need_score": 10, "tooling_need_score": 10,
        "ai_score": None, "ai_relevant": None,
    }
    attrs.update(kw)
    return type("L", (), attrs)()


def test_research_fit_summary_high_priority():
    lead = _fake_lead(1, priority="HIGH", casting_need_score=90,
                      cnc_need_score=70, tooling_need_score=60)
    research = research_gen.generate_research(lead, contacts=[], emails=[])
    assert research.fit_summary
    assert "HIGH" in research.fit_summary
    assert research.ai_scores["sales_priority"] == "HIGH"


def test_research_top_contacts_ranked_and_angle():
    lead = _fake_lead(2, priority="MEDIUM",
                      casting_need_score=50, cnc_need_score=50, tooling_need_score=50)
    contacts = [
        type("C", (), {"id": 10, "full_name": "Sam Buyer", "title": "Buyer",
                       "title_category": "procurement", "priority": "high",
                       "purchasing_score": 80, "email": "sam@acme.com"}),
        type("C", (), {"id": 11, "full_name": "Eve Eng", "title": "Engineer",
                       "title_category": "engineering", "priority": "medium",
                       "purchasing_score": 60, "email": "eve@acme.com"}),
    ]
    emails = [
        type("E", (), {"id": 20, "email": "sam@acme.com", "email_type": "personal",
                       "verification_status": "valid", "verification_score": 90}),
        type("E", (), {"id": 21, "email": "bad@acme.com", "email_type": "personal",
                       "verification_status": "invalid", "verification_score": 5}),
    ]
    research = research_gen.generate_research(lead, contacts=contacts, emails=emails)
    # Best contact (highest purchasing score) drives the recommended angle,
    # which references a concrete next step from the persona's CTA theme.
    assert research.recommended_angle
    assert "propose" in research.recommended_angle.lower()
    # Only the 'valid' e-mail is carried into the verified list.
    assert len(research.verified_emails) == 1
    assert research.verified_emails[0]["email"] == "sam@acme.com"
    # top_contacts sorted by purchasing_score desc.
    scores = [c["purchasing_score"] for c in research.top_contacts]
    assert scores == sorted(scores, reverse=True)


def test_research_ai_summary_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "app.ai_sales_agent.research.complete_json",
        lambda system, user, **kw: {"summary": "AI summary paragraph."},
    )
    lead = _fake_lead(3)
    research = research_gen.generate_research(lead, contacts=[], emails=[], use_ai=True)
    assert research.ai_summary == "AI summary paragraph."


# ---------------------------------------------------------------------------
# AI personalization engine
# ---------------------------------------------------------------------------
def test_personalization_deterministic(client, db):
    lead_id = _make_lead(client)
    lead = _load_lead(db, lead_id)
    email = personalization.generate_email(lead, db=db, use_ai=False, tone="professional")
    for key in ("subject", "opening", "body", "call_to_action", "to_name",
                "to_email", "role_category", "prompt_role", "used_ai", "greeting"):
        assert key in email
    assert email["used_ai"] is False
    assert isinstance(email["subject"], str) and email["subject"]


def test_personalization_contact_greeting(client, db):
    lead_id = _make_lead(client)
    lead = _load_lead(db, lead_id)
    contact = _seed_contact(db, lead_id)
    email = personalization.generate_email(lead, contact=contact, db=db, use_ai=False)
    assert email["to_name"] == "John Smith"
    assert email["to_email"] == "john.smith@acme.com"
    assert email["role_category"] == "procurement"
    # First-name greeting injected into the opening line.
    assert email["opening"].startswith("Dear John,")


def test_personalization_ai_merge(client, db, monkeypatch):
    lead_id = _make_lead(client)
    lead = _load_lead(db, lead_id)
    contact = _seed_contact(db, lead_id)
    monkeypatch.setattr(
        "app.ai_sales_agent.personalization.complete_json", _fake_complete_json
    )
    email = personalization.generate_email(lead, contact=contact, db=db, use_ai=True)
    # AI path applied and flagged.
    assert email["used_ai"] is True
    # Merged AI values override the deterministic baseline where non-empty.
    assert email["subject"].startswith("AI:")
    assert email["opening"] == "Hi John,"


# ---------------------------------------------------------------------------
# Draft CRUD (direct)
# ---------------------------------------------------------------------------
def test_crud_create_and_list(client, db):
    lead_id = _make_lead(client)
    draft = draft_crud.create(
        db, company_id=lead_id, subject="S: test", body="B: test body",
        status=DRAFT_STATUS_DRAFT, used_ai=False, quality_score=80,
    )
    assert draft.id is not None
    assert draft.company_id == lead_id

    rows = draft_crud.list_by_company(db, lead_id)
    assert len(rows) == 1
    fetched = draft_crud.get(db, draft.id)
    assert fetched is not None

    updated = draft_crud.update(db, draft, body="B: edited", status="approved")
    assert updated.body == "B: edited"
    assert updated.status == "approved"

    assert draft_crud.delete(db, draft.id) is True
    assert draft_crud.get(db, draft.id) is None


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------
def test_service_generate_draft(client, db):
    lead_id = _make_lead(client)
    _set_lead_scores(db, lead_id, sales_priority="HIGH", casting_need_score=90)
    result = svc.generate_draft(db, lead_id, use_ai=False, tone="professional")
    assert result is not None
    draft, research = result
    assert draft.company_id == lead_id
    assert draft.used_ai is False
    assert draft.quality_score is not None
    assert research.company == "Acme Castings"


def test_service_generate_draft_missing_company(db):
    assert svc.generate_draft(db, 999999, use_ai=False) is None
    assert svc.research_company(db, 999999) is None
    assert svc.personalize_only(db, 999999) is None


def test_service_score_draft(client, db):
    lead_id = _make_lead(client)
    draft, _ = svc.generate_draft(db, lead_id, use_ai=False)
    result = svc.score_draft(db, draft.id)
    assert result is not None
    re_draft, score = result
    assert score.overall is not None
    assert re_draft.quality_score == score.overall


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
def test_api_research(client, db):
    lead_id = _make_lead(client)
    _set_lead_scores(db, lead_id, sales_priority="HIGH", casting_need_score=90)
    r = client.post(f"/api/agent/research/{lead_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "Acme Castings"
    assert body["ai_scores"]["sales_priority"] == "HIGH"


def test_api_research_404(client):
    r = client.post("/api/agent/research/999999")
    assert r.status_code == 404


def test_api_create_draft(client, db):
    lead_id = _make_lead(client)
    r = client.post(f"/api/agent/draft/{lead_id}",
                    json={"use_ai": False, "tone": "professional"})
    assert r.status_code == 200
    data = r.json()
    assert data["company_id"] == lead_id
    assert data["used_ai"] is False
    assert data["quality_score"] is not None
    assert data["research"] is not None
    assert data["research"]["company"] == "Acme Castings"

    # Regression: the draft path must NOT create an outreach message.
    assert db.query(OutreachMessage).count() == 0


def test_api_create_draft_with_contact(client, db):
    lead_id = _make_lead(client)
    contact = _seed_contact(db, lead_id)
    r = client.post(f"/api/agent/draft/{lead_id}",
                    json={"contact_id": contact.id, "use_ai": False})
    assert r.status_code == 200
    data = r.json()
    assert data["contact_id"] == contact.id
    assert data["role_category"] == "procurement"
    assert data["to_name"] == "John Smith"


def test_api_create_draft_404(client):
    r = client.post("/api/agent/draft/999999", json={"use_ai": False})
    assert r.status_code == 404


def test_api_personalize(client):
    lead_id = _make_lead(client)
    r = client.post("/api/agent/personalize",
                    json={"company_id": lead_id, "use_ai": False})
    assert r.status_code == 200
    data = r.json()
    for key in ("subject", "opening", "body", "call_to_action", "used_ai"):
        assert key in data


def test_api_personalize_404(client):
    r = client.post("/api/agent/personalize", json={"company_id": 999999})
    assert r.status_code == 404


def test_api_draft_crud_lifecycle(client):
    lead_id = _make_lead(client)
    create = client.post(f"/api/agent/draft/{lead_id}", json={"use_ai": False})
    assert create.status_code == 200
    draft_id = create.json()["id"]

    # List
    lst = client.get(f"/api/agent/drafts/{lead_id}")
    assert lst.status_code == 200
    assert any(d["id"] == draft_id for d in lst.json())

    # Get
    get_r = client.get(f"/api/agent/draft/{draft_id}")
    assert get_r.status_code == 200
    assert get_r.json()["id"] == draft_id

    # Update
    upd = client.put(f"/api/agent/draft/{draft_id}",
                     json={"status": "approved", "body": "Edited body."})
    assert upd.status_code == 200
    assert upd.json()["status"] == "approved"
    assert upd.json()["body"] == "Edited body."

    # Delete
    dele = client.delete(f"/api/agent/draft/{draft_id}")
    assert dele.status_code == 200
    assert dele.json()["deleted"] is True
    assert client.get(f"/api/agent/draft/{draft_id}").status_code == 404


def test_api_get_draft_404(client):
    assert client.get("/api/agent/draft/999999").status_code == 404
    assert client.delete("/api/agent/draft/999999").status_code == 404
    assert client.put("/api/agent/draft/999999",
                      json={"body": "x"}).status_code == 404


def test_api_quality_endpoint(client):
    r = client.post("/api/agent/quality", json={
        "subject": "Precision die casting for Acme Castings",
        "body": "Dear John, we would like to schedule a review. Best regards",
        "company": "Acme Castings", "to_name": "John",
    })
    assert r.status_code == 200
    d = r.json()
    assert "overall" in d and "dimensions" in d


def test_api_score_draft_endpoint(client):
    lead_id = _make_lead(client)
    create = client.post(f"/api/agent/draft/{lead_id}", json={"use_ai": False})
    draft_id = create.json()["id"]
    r = client.post(f"/api/agent/draft/{draft_id}/score")
    assert r.status_code == 200
    assert "quality_breakdown" in r.json()
    assert r.json()["quality_breakdown"]["overall"] is not None


def test_api_score_draft_404(client):
    assert client.post("/api/agent/draft/999999/score").status_code == 404
