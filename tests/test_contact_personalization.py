"""Phase 4 Stage 4 — Contact-Aware Outreach Personalization tests.

Covers:
  * personalised greeting "Dear {first_name}," when a contact name exists
  * fixed fallback "Dear Purchasing Manager," when no contact name
  * template variables exposing contact_name / first_name / contact_email
  * recipient_name / recipient_email persisted on the generated draft
  * the greeting survives the full generate-email API path

The generator tests run WITHOUT the OpenAI LLM (deterministic render path).
"""
from fastapi.testclient import TestClient

from app.outreach.context import build_context
from app.outreach.email_generator import generate_email, _context_variables


def _context(**kw):
    base = dict(
        company="Acme Castings GmbH",
        industry="automotive",
        country="Germany",
        business_type="OEM Tier-1",
        materials="aluminum, ADC12",
        manufacturing_process="high pressure die casting",
        contact_role="Purchasing Manager",
        lead_score=78,
    )
    base.update(kw)
    return build_context(**base)


def _generate(ctx):
    return generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )


# ---------------------------------------------------------------------------
# Greeting logic
# ---------------------------------------------------------------------------
def test_greeting_uses_first_name_when_contact_available():
    ctx = _context(contact_name="Haruto Tanaka", contact_email="h.tanaka@acme.example.com")
    out = _generate(ctx)
    assert out["opening"].startswith("Dear Haruto,")
    # Company framing still present in the opening.
    assert ctx.company in out["opening"]


def test_greeting_uses_first_name_for_multi_part_name():
    ctx = _context(contact_name="Dr. Maria Elena Rossi")
    out = _generate(ctx)
    assert out["opening"].startswith("Dear Dr.,")


def test_greeting_fallback_when_no_contact_name():
    ctx = _context(contact_name="", contact_email="")
    out = _generate(ctx)
    assert out["opening"].startswith("Dear Purchasing Manager,")
    assert ctx.company in out["opening"]


def test_context_variables_expose_contact_fields():
    ctx = _context(
        contact_name="Haruto Tanaka", contact_email="h.tanaka@acme.example.com"
    )
    variables = _context_variables(ctx)
    assert variables["contact_name"] == "Haruto Tanaka"
    assert variables["first_name"] == "Haruto"
    assert variables["contact_email"] == "h.tanaka@acme.example.com"
    assert variables["greeting"] == "Dear Haruto,"
    assert "{first_name}" not in variables["greeting"]  # pre-rendered


def test_context_variables_fallback_greeting():
    ctx = _context(contact_name="", contact_email="")
    variables = _context_variables(ctx)
    assert variables["first_name"] == ""
    assert variables["greeting"] == "Dear Purchasing Manager,"


# ---------------------------------------------------------------------------
# Recipient stored on the draft (full API path)
# ---------------------------------------------------------------------------
def _make_lead(client, *, name, contact_name=None, contact_email=None):
    payload = {
        "name": name,
        "website": f"https://{name.lower().replace(' ', '-')}.example.com",
        "industry": "automotive",
        "materials": "aluminum",
        "manufacturing_process": "high pressure die casting",
        "contact_role": "Purchasing Manager",
    }
    if contact_name:
        payload["contact_name"] = contact_name
    if contact_email:
        payload["contact_email"] = contact_email
    r = client.post("/leads", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


def test_recipient_stored_on_draft_with_contact(client: TestClient):
    lead_id = _make_lead(
        client,
        name="Contact Draft Co",
        contact_name="Yuki Sato",
        contact_email="y.sato@contactdraft.example.com",
    )
    r = client.post(f"/leads/{lead_id}/generate-email")
    assert r.status_code == 201
    draft = r.json()
    assert draft["recipient_name"] == "Yuki Sato"
    assert draft["recipient_email"] == "y.sato@contactdraft.example.com"
    assert "Dear Yuki," in draft["body"]


def test_recipient_missing_on_draft_without_contact(client: TestClient):
    lead_id = _make_lead(client, name="No Contact Draft Co")
    r = client.post(f"/leads/{lead_id}/generate-email")
    assert r.status_code == 201
    draft = r.json()
    assert draft["recipient_name"] is None
    assert draft["recipient_email"] is None
    assert "Dear Purchasing Manager," in draft["body"]
