"""Phase 14.2 — AI Personalized Outreach Preparation.

Offline (no network, no LLM) coverage of the personalization layer:

  * context contains company / contact information
  * ranked contact information (ranking_score/confidence/reason) is included
  * deterministic prompt generation (same input -> same output)
  * missing fields are handled safely (no crash, graceful generic draft)
  * structured output shape (subject / body / personalization_reason / score)
"""
from app.models.contact import Contact
from app.models.lead import CompanyLead
from app.models.manufacturing_capability import ManufacturingCapability
from app.outreach.personalization import (
    PersonalizationContext,
    PersonalizationService,
    PersonalizedEmail,
    build_personalization_context,
    generate_personalized_email_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_lead(**overrides):
    defaults = dict(
        name="Acme Powertrain",
        industry="Automotive",
        country="Germany",
        description="Tier-1 supplier of EV drive units.",
        materials="ADC12,A380",
        manufacturing_process="die casting, CNC machining",
        casting_need_score=88,
        cnc_need_score=70,
        tooling_need_score=65,
        sales_priority="HIGH",
        business_type="Manufacturer",
        website="https://acme.example.com",
    )
    defaults.update(overrides)
    return CompanyLead(**defaults)


def _make_contact(**overrides):
    defaults = dict(
        lead_id=1,
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role="Purchasing Manager",
        title="Purchasing Manager",
        title_category="procurement",
        seniority="senior",
        email="jane.doe@acme.example.com",
        ranking_score=92,
        ranking_confidence="high",
        ranking_reason="category=procurement(+40); ...",
    )
    defaults.update(overrides)
    return Contact(**defaults)


def _make_cap(**overrides):
    defaults = dict(
        process="die casting",
        machine_type="cold chamber",
        tonnage=650,
        material_compatibility="ADC12,A380,AZ91D",
        tolerance_capability="±0.05mm",
        active=True,
    )
    defaults.update(overrides)
    return ManufacturingCapability(**defaults)


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------
def test_context_contains_company_and_contact_info():
    lead = _make_lead()
    contact = _make_contact()
    ctx = build_personalization_context(lead, contact)

    assert isinstance(ctx, PersonalizationContext)
    assert ctx.company_name == "Acme Powertrain"
    assert ctx.company_industry == "Automotive"
    assert ctx.company_materials == ["ADC12", "A380"]
    assert ctx.company_processes == ["die casting", "CNC machining"]
    assert ctx.contact_name == "Jane Doe"
    assert ctx.contact_role == "Purchasing Manager"
    assert ctx.contact_email == "jane.doe@acme.example.com"


def test_context_includes_ranked_contact_information():
    lead = _make_lead()
    contact = _make_contact(
        ranking_score=92, ranking_confidence="high", ranking_reason="cat=procurement"
    )
    ctx = build_personalization_context(lead, contact)

    assert ctx.ranking_score == 92
    assert ctx.ranking_confidence == "high"
    assert ctx.ranking_reason == "cat=procurement"


def test_context_matches_capabilities_to_prospect_materials():
    lead = _make_lead(materials="ADC12,A380")
    contact = _make_contact()
    cap = _make_cap(material_compatibility="ADC12,A380,AZ91D")
    ctx = build_personalization_context(lead, contact, capabilities=[cap])

    assert ctx.capability_match, "expected at least one matched capability"
    assert "ADC12" in ctx.capability_match[0]


def test_context_passes_capabilities_as_dicts():
    lead = _make_lead(materials="ADC12")
    contact = _make_contact()
    cap_dict = {
        "process": "die casting",
        "tonnage": 650,
        "material_compatibility": "ADC12",
    }
    ctx = build_personalization_context(lead, contact, capabilities=[cap_dict])
    assert ctx.capability_match
    assert isinstance(ctx.capabilities[0], dict)


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------
def test_prompt_output_shape():
    ctx = build_personalization_context(_make_lead(), _make_contact())
    email = generate_personalized_email_prompt(ctx)

    assert isinstance(email, PersonalizedEmail)
    assert isinstance(email.subject, str) and email.subject
    assert isinstance(email.body, str) and email.body
    assert isinstance(email.personalization_reason, str) and email.personalization_reason
    assert isinstance(email.personalization_score, int)
    assert 0 <= email.personalization_score <= 100


def test_prompt_is_deterministic():
    ctx = build_personalization_context(_make_lead(), _make_contact())
    a = generate_personalized_email_prompt(ctx)
    b = generate_personalized_email_prompt(ctx)
    assert a.subject == b.subject
    assert a.body == b.body
    assert a.personalization_reason == b.personalization_reason
    assert a.personalization_score == b.personalization_score


def test_prompt_includes_contact_name_and_company():
    ctx = build_personalization_context(_make_lead(), _make_contact())
    email = generate_personalized_email_prompt(ctx)
    assert "Jane" in email.body
    assert "Acme Powertrain" in email.subject or "Acme Powertrain" in email.body


def test_prompt_includes_ranking_when_present():
    ctx = build_personalization_context(
        _make_lead(), _make_contact(ranking_score=92, ranking_confidence="high")
    )
    email = generate_personalized_email_prompt(ctx)
    assert "92/100" in email.body
    assert "ranking_score 92/100" in email.personalization_reason


def test_prompt_handles_missing_fields_safely():
    # Bare company / contact with no enrichment -> must not raise.
    lead = CompanyLead(name=None)
    contact = Contact(lead_id=1)
    ctx = build_personalization_context(lead, contact)
    email = generate_personalized_email_prompt(ctx)

    assert ctx.company_name == "your company"
    assert ctx.contact_name == ""
    assert email.personalization_score == 0
    assert "generic" in email.personalization_reason
    assert isinstance(email.body, str) and email.body.strip()


def test_prompt_full_context_scores_100():
    lead = _make_lead(
        description="Tier-1 supplier of EV drive units.",
        materials="ADC12,A380",
        manufacturing_process="die casting, CNC machining",
    )
    contact = _make_contact(
        ranking_score=92, ranking_confidence="high", ranking_reason="cat=procurement"
    )
    cap = _make_cap()
    ctx = build_personalization_context(lead, contact, capabilities=[cap])
    email = generate_personalized_email_prompt(ctx)
    # Every signal present (name, role, industry, materials, processes,
    # ranking, capability match, description) -> 100.
    assert email.personalization_score == 100


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------
def test_service_personalize_with_db(db):
    lead = _make_lead()
    db.add(lead)
    db.commit()
    db.refresh(lead)

    contact = _make_contact(lead_id=lead.id)
    db.add(contact)
    cap = _make_cap()
    db.add(cap)
    db.commit()
    db.refresh(contact)

    svc = PersonalizationService(db)
    email = svc.personalize(lead, contact)

    assert isinstance(email, PersonalizedEmail)
    assert email.personalization_score > 0
    assert "Jane" in email.body
    # Capability was loaded from DB and matched against ADC12.
    assert email.personalization_score == 100
