"""Tests for the Phase 12.2 Quotation Intelligence Engine."""
import pytest

from app.models.quotation import (
    Quote,
    QuoteLineItem,
    QuoteVersion,
    create_quote_from_requirement,
)
from app.models.product_requirement import ProductRequirement
from app.models.cost_rate import CostRate
from app.models.lead import CompanyLead
from app.quotation.estimator import (
    estimate_quote,
    match_capability,
    RequirementLike,
)


def _seed_rates(db):
    rows = [
        CostRate(category="material", code="ADC12", unit="kg", rate=5.0, currency="USD", is_default=True),
        CostRate(category="machine_hour", code="dc_machine", unit="hour", rate=80.0, currency="USD", is_default=True),
        CostRate(category="machine_hour", code="cnc_machine", unit="hour", rate=60.0, currency="USD", is_default=True),
        CostRate(category="tooling", code="mold", unit="lot", rate=5000.0, currency="USD", is_default=True),
        CostRate(category="finishing", code="anodizing", unit="piece", rate=0.5, currency="USD", is_default=True),
        CostRate(category="overhead", code="factory", unit="pct", rate=10.0, currency="USD", is_default=True),
    ]
    for r in rows:
        db.add(r)
    db.commit()


# ---------------------------------------------------------------------------
# Model creation
# ---------------------------------------------------------------------------
def test_quote_model_creation(db):
    q = Quote(status="draft", currency="USD")
    db.add(q)
    db.commit()
    db.refresh(q)
    assert q.id is not None
    assert q.version == 1
    assert q.status == "draft"
    assert q.currency == "USD"
    assert q.used_ai is False


def test_quote_line_item_creation(db):
    q = Quote(status="draft")
    db.add(q)
    db.commit()
    db.refresh(q)
    li = QuoteLineItem(
        quote_id=q.id, line_type="material", description="Material",
        quantity=10, unit="kg", unit_rate=5.0, amount=50.0,
    )
    db.add(li)
    db.commit()
    db.refresh(li)
    assert li.id is not None
    assert li.quote_id == q.id
    assert li.used_ai is False


def test_quote_version_creation(db):
    q = Quote(status="draft")
    db.add(q)
    db.commit()
    db.refresh(q)
    v = QuoteVersion(quote_id=q.id, version=1, snapshot="{}", source="deterministic")
    db.add(v)
    db.commit()
    db.refresh(v)
    assert v.id is not None
    assert v.quote_id == q.id


# ---------------------------------------------------------------------------
# FK SET NULL (nullable FKs)
# ---------------------------------------------------------------------------
def test_quote_nullable_fks(db):
    q = Quote(
        status="draft", company_id=None,
        opportunity_id=None, rfq_id=None, requirement_id=None,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    assert q.company_id is None
    lead = CompanyLead(name="Acme Castings")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    q2 = Quote(status="draft", company_id=lead.id)
    db.add(q2)
    db.commit()
    db.refresh(q2)
    assert q2.company_id == lead.id


# ---------------------------------------------------------------------------
# Quote line cascade (CASCADE delete)
# ---------------------------------------------------------------------------
def test_quote_line_cascade(db):
    q = Quote(status="draft")
    db.add(q)
    db.commit()
    db.refresh(q)
    li = QuoteLineItem(quote_id=q.id, line_type="material", amount=10.0)
    db.add(li)
    db.commit()
    db.delete(q)
    db.commit()
    remaining = db.query(QuoteLineItem).filter(QuoteLineItem.quote_id == q.id).all()
    assert remaining == []


# ---------------------------------------------------------------------------
# Deterministic cost calculation
# ---------------------------------------------------------------------------
def test_deterministic_cost_calculation(db):
    _seed_rates(db)
    rates = db.query(CostRate).all()
    req = RequirementLike(
        weight=0.5, material="ADC12", process="die_casting",
        annual_volume=1000, finishing="anodizing",
    )
    est = estimate_quote(req, capabilities=[], rates=rates, currency="USD", margin_pct=25.0, use_ai=False)
    assert est["total_material_cost"] == 2500.0
    assert est["total_machine_cost"] == 1600.0
    assert est["total_cnc_cost"] == 0.0
    assert est["total_tooling_cost"] == 5000.0
    assert est["total_finishing_cost"] == 500.0
    assert est["subtotal"] == 9600.0
    assert est["total_overhead"] == 960.0
    assert est["total_cost"] == 10560.0
    assert est["used_ai"] is False


def test_margin_calculation(db):
    _seed_rates(db)
    rates = db.query(CostRate).all()
    req = RequirementLike(
        weight=0.5, material="ADC12", process="die_casting",
        annual_volume=1000, finishing="anodizing",
    )
    est = estimate_quote(req, capabilities=[], rates=rates, currency="USD", margin_pct=25.0, use_ai=False)
    # suggested_price = total_cost / (1 - margin)
    assert est["suggested_price"] == pytest.approx(14080.0, rel=1e-6)
    assert est["margin_amount"] == pytest.approx(3520.0, rel=1e-6)
    assert est["margin_pct"] == 25.0


def test_estimator_without_ai_does_not_set_flag(db):
    _seed_rates(db)
    rates = db.query(CostRate).all()
    req = RequirementLike(
        weight=0.5, material="ADC12", process="die_casting",
        annual_volume=1000, finishing="anodizing",
    )
    est = estimate_quote(req, capabilities=[], rates=rates, currency="USD", margin_pct=25.0, use_ai=False)
    assert est["used_ai"] is False
    assert est["explanation"] == ""


def test_estimator_ai_only_refines_margin(db, monkeypatch):
    _seed_rates(db)
    rates = db.query(CostRate).all()
    req = RequirementLike(
        weight=0.5, material="ADC12", process="die_casting",
        annual_volume=1000, finishing="anodizing",
    )

    def fake_complete_json(system, user, *, temperature=0.3, max_tokens=None):
        return {
            "margin_pct": 30.0,
            "price_min": 12000,
            "price_max": 16000,
            "explanation": "Tight market.",
        }

    monkeypatch.setattr("app.quotation.estimator.complete_json", fake_complete_json)
    est = estimate_quote(req, capabilities=[], rates=rates, currency="USD", margin_pct=25.0, use_ai=True)
    assert est["used_ai"] is True
    assert est["margin_pct"] == 30.0
    assert est["explanation"] == "Tight market."
    # cost lines unchanged by AI
    assert est["total_cost"] == 10560.0
    assert est["suggested_price"] == pytest.approx(10560.0 / 0.70, rel=1e-6)
    assert len(est["lines"]) == 5


def test_capability_match(db):
    from app.models.manufacturing_capability import ManufacturingCapability

    caps = [
        ManufacturingCapability(
            process="die_casting", material_compatibility="ADC12,A380",
            max_part_weight=5.0, active=True,
        )
    ]
    req = RequirementLike(weight=0.5, material="ADC12", process="die_casting")
    assert match_capability(req, caps) is True
    req2 = RequirementLike(weight=10.0, material="ADC12", process="die_casting")
    assert match_capability(req2, caps) is False
    # unknown when no capability data
    assert match_capability(req, []) is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def test_create_quote_from_requirement(db):
    _seed_rates(db)
    req = ProductRequirement(
        material="ADC12", process="die_casting", weight=0.5,
        annual_volume=1000, finishing="anodizing",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    quote = create_quote_from_requirement(db, req, use_ai=False, margin_pct=25.0)
    assert quote.id is not None
    assert quote.status == "draft"
    assert quote.subtotal == 9600.0
    assert quote.total_amount == pytest.approx(14080.0, rel=1e-6)
    assert quote.margin_pct == 25.0
    assert quote.used_ai is False
    assert len(quote.lines) == 5
    assert len(quote.versions) == 1
    assert quote.versions[0].source == "deterministic"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
def test_api_estimate(client, db):
    _seed_rates(db)
    req = ProductRequirement(
        material="ADC12", process="die_casting", weight=0.5,
        annual_volume=1000, finishing="anodizing",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    resp = client.post(
        "/api/quotation/estimate",
        json={"requirement_id": req.id, "margin_pct": 25.0, "use_ai": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 10560.0
    assert data["suggested_price"] == pytest.approx(14080.0, rel=1e-6)
    assert data["used_ai"] is False
    assert len(data["lines"]) == 5


def test_api_estimate_missing_requirement(client, db):
    resp = client.post("/api/quotation/estimate", json={"requirement_id": 99999})
    assert resp.status_code == 404


def test_api_create_and_get(client, db):
    _seed_rates(db)
    req = ProductRequirement(
        material="ADC12", process="die_casting", weight=0.5,
        annual_volume=1000, finishing="anodizing",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    resp = client.post(
        "/api/quotation",
        json={"requirement_id": req.id, "margin_pct": 25.0, "use_ai": False},
    )
    assert resp.status_code == 201
    q = resp.json()
    qid = q["id"]
    assert q["total_amount"] == pytest.approx(14080.0, rel=1e-6)
    assert len(q["lines"]) == 5
    assert len(q["versions"]) == 1

    lst = client.get("/api/quotation").json()
    assert any(x["id"] == qid for x in lst)

    one = client.get(f"/api/quotation/{qid}").json()
    assert one["id"] == qid
    assert len(one["lines"]) == 5


def test_api_get_missing_quote(client, db):
    resp = client.get("/api/quotation/99999")
    assert resp.status_code == 404
