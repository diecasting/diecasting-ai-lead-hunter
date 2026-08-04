"""Phase 4 Stage 2 — AI Outreach Personalization Engine tests.

Covers the pieces built in Stage 2:

  * role-specific personalization  — Purchasing Manager / Engineering Manager /
    Supplier Quality Manager each select the right role template and produce
    role-flavoured subject + body copy.
  * industry context              — automotive / ev / hydraulic / cnc / pump /
    gearbox / tooling / machinery still generate valid emails with the right
    industry template, even when no role is supplied.
  * fallback templates            — an unknown role falls back to
    ``role_generic.md``; an unknown industry falls back to
    ``industrial_equipment.md``.
  * email quality scoring         — personalization / relevance / spam_risk
    behave correctly (personalised email outscores generic placeholder copy;
    spam phrases raise spam_risk; an empty email is maximally risky).

Note: these tests run WITHOUT the OpenAI LLM (deterministic render path) so
they are hermetic and fast.
"""
import pytest

from app.outreach.context import build_context, CustomerContext
from app.outreach.email_generator import (
    generate_email,
    _detect_role_template,
    _detect_industry,
)
from app.outreach.email_quality import (
    personalization_score,
    relevance_score,
    spam_risk_score,
    score_email_quality,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _make_context(role: str, industry: str, **kw) -> CustomerContext:
    """Build a CustomerContext for a given role + industry with sensible defaults."""
    base = dict(
        company="Acme Castings GmbH",
        industry=industry,
        country="Germany",
        business_type="OEM Tier-1",
        products=f"{industry} components",
        materials="aluminum, ADC12",
        manufacturing_process="high pressure die casting, CNC",
        description=f"{industry} supplier producing precision cast housings",
        procurement_signals={"type": "casting", "score": 72},
        contact_role=role,
        lead_score=78,
        priority="MEDIUM",
    )
    base.update(kw)
    return build_context(**base)


# ---------------------------------------------------------------------------
# 1. Different ROLES — each selects the right template + role-flavoured copy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role,expected_template",
    [
        ("Purchasing Manager", "purchasing_manager.md"),
        ("Strategic Sourcing", "purchasing_manager.md"),
        ("Engineering Manager", "engineering.md"),
        ("Component Engineering", "engineering.md"),
        ("Supplier Quality Manager", "supplier_quality.md"),
        ("SQE", "supplier_quality.md"),
    ],
)
def test_detect_role_template_maps_known_roles(role, expected_template):
    assert _detect_role_template(role) == expected_template


def test_purchasing_role_emphasises_cost_and_capacity():
    ctx = _make_context("Purchasing Manager", "automotive")
    out = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    body = (out["subject"] + out["opening"] + out["body"]).lower()
    # Purchasing focus: commercial / supply-chain / capacity language.
    assert any(k in body for k in ["cost", "capacity", "supply", "price", "source"])
    # The role template was used (role_version body is non-empty -> preferred).
    assert out["contact_role"] == "Purchasing Manager"
    assert out["body"].strip() != ""


def test_engineering_role_emphasises_tolerance_material_process():
    ctx = _make_context("Engineering Manager", "hydraulic")
    out = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    body = (out["subject"] + out["opening"] + out["body"]).lower()
    # Engineering focus: technical / tolerance / material / process language.
    assert any(k in body for k in ["tolerance", "material", "process", "adc12", "dfm"])
    assert "Engineering Manager" in out["contact_role"]


def test_supplier_quality_role_emphasises_ppap_certification():
    ctx = _make_context("Supplier Quality Manager", "ev")
    out = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    body = (out["subject"] + out["opening"] + out["body"]).lower()
    # Supplier Quality focus: quality system / PPAP / certification language.
    assert any(k in body for k in ["ppap", "iatf", "quality", "certif", "apqp"])
    assert "Supplier Quality Manager" in out["contact_role"]


# ---------------------------------------------------------------------------
# 2. Different INDUSTRIES — valid email + correct industry template
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "industry,expected_template",
    [
        ("automotive", "automotive.md"),
        ("electric vehicle", "ev.md"),
        ("battery housing", "ev.md"),
        ("hydraulic", "hydraulic.md"),
        ("pump", "pump.md"),
        ("gearbox", "gearbox.md"),
        ("cnc machining", "cnc.md"),
        ("tooling", "tooling.md"),
        ("industrial robotics", "industrial_equipment.md"),
    ],
)
def test_detect_industry_maps_known_industries(industry, expected_template):
    assert _detect_industry(industry) == expected_template


@pytest.mark.parametrize(
    "industry",
    ["automotive", "ev", "hydraulic", "pump", "gearbox", "cnc machining", "tooling"],
)
def test_industry_email_generates_without_role(industry):
    """Industry context still produces a valid email even with no role hint."""
    ctx = _make_context("", industry)
    out = generate_email(
        {"company": ctx.company, "industry": industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    assert out["subject"].strip()
    assert out["body"].strip()
    # Company name should be personalised into the opening.
    assert ctx.company in out["opening"]


# ---------------------------------------------------------------------------
# 3. FALLBACK templates
# ---------------------------------------------------------------------------
def test_unknown_role_falls_back_to_role_generic():
    assert _detect_role_template("Chief Financial Officer") == "role_generic.md"
    assert _detect_role_template("") == "role_generic.md"
    assert _detect_role_template("Some Random Title XYZ") == "role_generic.md"


def test_unknown_industry_falls_back_to_industrial_equipment():
    assert _detect_industry("underwater basket weaving") == "industrial_equipment.md"
    assert _detect_industry("") == "industrial_equipment.md"


def test_fallback_role_template_still_generates_valid_email():
    """An unknown role must not crash; it should use role_generic.md copy."""
    ctx = _make_context("Chief Financial Officer", "automotive")
    out = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    assert out["subject"].strip()
    assert out["body"].strip()
    # role_generic still personalises by company name.
    assert ctx.company in out["opening"]


# ---------------------------------------------------------------------------
# 4. EMAIL QUALITY SCORING
# ---------------------------------------------------------------------------
def test_personalized_email_outscores_generic_placeholder():
    ctx = _make_context("Purchasing Manager", "automotive")
    personalised = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    personalised_text = "\n".join(
        [personalised["subject"], personalised["opening"], personalised["body"]]
    )
    generic = (
        "Dear Sir/Madam,\n\nWe would like to introduce our services to your company. "
        "Your company may benefit from our die casting capabilities.\n\n"
        "Please let us know if interested."
    )
    assert personalization_score(personalised_text, ctx) > personalization_score(generic, ctx)


def test_relevance_score_rewards_signal_mentions():
    ctx = _make_context("Engineering Manager", "hydraulic",
                        materials="aluminum, A380",
                        manufacturing_process="high pressure die casting")
    email = (
        "Dear Acme Castings GmbH Team,\n\nWe specialise in high pressure die casting "
        "of aluminum components for hydraulic systems. Our A380 material expertise and "
        "tight tolerance process fit your programs. Can we schedule a call?\n"
    )
    score = relevance_score(email, ctx)
    assert score >= 50  # signals (materials/process/industry) are all mentioned
    # A body with none of the signals should score lower.
    empty_ctx = build_context(company="Acme", industry="hydraulic",
                              materials="aluminum", manufacturing_process="hpdc")
    low = relevance_score("Dear Acme Team, we offer great services. Call us.", empty_ctx)
    assert score > low


def test_spam_phrases_raise_spam_risk():
    clean_ctx = _make_context("Purchasing Manager", "automotive")
    clean = (
        "Dear Acme Castings GmbH Team,\n\nWe noticed your aluminum die casting programs "
        "and would like to discuss capacity for automotive housings. Could we schedule a call?\n"
    )
    spammy = (
        "URGENT! FREE OFFER! Buy now at the BEST PRICE, LIMITED TIME, 100% RISK FREE! "
        "Click here to claim your discount! Act now before supplies run out!\n"
    )
    assert spam_risk_score(spammy, clean_ctx) > spam_risk_score(clean, clean_ctx)
    # Empty email is maximally risky.
    assert spam_risk_score("", clean_ctx) == 100


def test_score_email_quality_returns_all_axes():
    ctx = _make_context("Supplier Quality Manager", "ev")
    out = generate_email(
        {"company": ctx.company, "industry": ctx.industry, "materials": ctx.materials,
         "manufacturing_process": ctx.manufacturing_process},
        use_llm=False,
        context=ctx,
    )
    text = "\n".join([out["subject"], out["opening"], out["body"], out["call_to_action"]])
    result = score_email_quality(text, ctx)
    assert set(result.keys()) == {
        "personalization_score", "relevance_score", "spam_risk_score", "quality"
    }
    for k in ("personalization_score", "relevance_score", "spam_risk_score", "quality"):
        assert 0 <= result[k] <= 100
    # quality blends the three axes; it must be a weighted combination.
    expected_quality = int(
        result["personalization_score"] * 0.4
        + result["relevance_score"] * 0.4
        + (100 - result["spam_risk_score"]) * 0.2
    )
    assert result["quality"] == expected_quality


def test_quality_gate_blocks_generic_mass_blast():
    """A generic, spammy draft should score poorly on quality."""
    ctx = _make_context("Purchasing Manager", "automotive")
    spammy = (
        "Dear Sir/Madam, YOUR COMPANY can SAVE with our CHEAP services! "
        "100% RISK FREE, BUY NOW, LIMITED TIME! Click here!\n"
    )
    result = score_email_quality(spammy, ctx)
    # Generic placeholder + spam phrases -> low personalization + high spam risk.
    assert result["personalization_score"] < 30
    assert result["spam_risk_score"] >= 40
    assert result["quality"] < 50
