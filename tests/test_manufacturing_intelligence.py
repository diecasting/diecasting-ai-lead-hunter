"""Tests for the Phase 12.1 Manufacturing Intelligence Foundation.

Covers the three foundation models (ManufacturingCapability, CostRate,
ProductRequirement): creation, default values, nullable FKs, the
CostRate unique constraint, and FK relationships. No quotation engine,
pricing or AI logic is exercised here — that is later Phase 12 work.
"""
import pytest
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.models import (
    CompanyLead,
    CostRate,
    ManufacturingCapability,
    Opportunity,
    ProductRequirement,
    ReplyAnalysis,
    ReplyRFQExtraction,
)


# ---------------------------------------------------------------------------
# ManufacturingCapability
# ---------------------------------------------------------------------------
def test_manufacturing_capability_creation(db):
    cap = ManufacturingCapability(
        process="die_casting",
        machine_type="cold_chamber_press",
        tonnage=800,
        material_compatibility="ADC12,A380,AZ91D",
        max_part_weight=2.5,
        tolerance_capability="±0.05mm",
        active=True,
    )
    db.add(cap)
    db.commit()
    db.refresh(cap)
    assert cap.id is not None
    assert cap.process == "die_casting"
    assert cap.tonnage == 800
    assert cap.material_compatibility == "ADC12,A380,AZ91D"


def test_manufacturing_capability_default_active(db):
    cap = ManufacturingCapability(process="cnc_machining")
    db.add(cap)
    db.commit()
    db.refresh(cap)
    # active defaults to True.
    assert cap.active is True


# ---------------------------------------------------------------------------
# CostRate
# ---------------------------------------------------------------------------
def test_cost_rate_creation(db):
    rate = CostRate(
        category="material",
        code="ADC12",
        label="ADC12 alloy",
        unit="kg",
        rate=2.5,
        currency="USD",
        is_default=True,
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    assert rate.id is not None
    assert rate.rate == 2.5
    assert rate.is_default is True


def test_cost_rate_defaults(db):
    rate = CostRate(category="machine_hour", code="dc_800t", rate=45.0)
    db.add(rate)
    db.commit()
    db.refresh(rate)
    assert rate.is_default is False
    assert rate.source == "manual"
    assert rate.currency is None


def test_cost_rate_unique_constraint(db):
    # The unique constraint covers (category, code, effective_from). With a
    # concrete effective_from the two rows collide and the DB must reject r2.
    r1 = CostRate(
        category="material", code="ADC12", rate=2.5,
        currency="USD", effective_from=date(2026, 1, 1),
    )
    db.add(r1)
    db.commit()
    r2 = CostRate(
        category="material", code="ADC12", rate=3.0,
        currency="USD", effective_from=date(2026, 1, 1),
    )
    db.add(r2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cost_rate_null_effective_from_allows_duplicates(db):
    # SQLite/PostgreSQL treat NULL effective_from as distinct, so multiple
    # "current" (NULL-effective) rows with the same (category, code) are
    # permitted by this constraint. Document the behaviour explicitly.
    r1 = CostRate(category="material", code="ADC12", rate=2.5)
    r2 = CostRate(category="material", code="ADC12", rate=3.0)
    db.add_all([r1, r2])
    db.commit()  # must not raise
    assert r1.id is not None and r2.id is not None


def test_cost_rate_unique_allows_different_code(db):
    r1 = CostRate(category="material", code="ADC12", rate=2.5)
    r2 = CostRate(category="material", code="A380", rate=2.8)
    db.add_all([r1, r2])
    db.commit()  # must not raise
    assert r1.id is not None and r2.id is not None


# ---------------------------------------------------------------------------
# ProductRequirement
# ---------------------------------------------------------------------------
def test_product_requirement_creation(db):
    pr = ProductRequirement(
        weight=0.45,
        material="ADC12",
        process="die_casting",
        annual_volume=50000,
        tolerance="±0.05mm",
        finishing="anodizing",
        complexity="medium",
        used_ai=True,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    assert pr.id is not None
    assert pr.weight == 0.45
    assert pr.material == "ADC12"
    assert pr.annual_volume == 50000
    assert pr.used_ai is True


def test_product_requirement_default_used_ai(db):
    pr = ProductRequirement(material="A380")
    db.add(pr)
    db.commit()
    db.refresh(pr)
    assert pr.used_ai is False


def test_product_requirement_nullable_foreign_keys(db):
    # Every FK is nullable -> a requirement with no links must persist.
    pr = ProductRequirement(material="ADC12")
    db.add(pr)
    db.commit()
    db.refresh(pr)
    assert pr.rfq_id is None
    assert pr.opportunity_id is None
    assert pr.company_id is None


def test_product_requirement_opportunity_relationship(db):
    opp = Opportunity(amount=1000.0)  # currency defaults to USD
    db.add(opp)
    db.commit()
    db.refresh(opp)
    pr = ProductRequirement(opportunity_id=opp.id, material="ADC12")
    db.add(pr)
    db.commit()
    db.refresh(pr)
    assert pr.opportunity is not None
    assert pr.opportunity.id == opp.id
    # The backref on Opportunity resolves too.
    assert pr in opp.product_requirements


def test_product_requirement_rfq_relationship(db):
    # Minimal chain: CompanyLead -> ReplyAnalysis -> ReplyRFQExtraction.
    company = CompanyLead(name="Acme Castings")
    db.add(company)
    db.commit()
    db.refresh(company)

    analysis = ReplyAnalysis(
        lead_id=company.id, reply_text="We need a quote", intent="rfq_request"
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rfq = ReplyRFQExtraction(
        analysis_id=analysis.id, product="bracket", material="ADC12", quantity="10000"
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)

    pr = ProductRequirement(rfq_id=rfq.id, company_id=company.id, material="ADC12")
    db.add(pr)
    db.commit()
    db.refresh(pr)

    assert pr.rfq is not None
    assert pr.rfq.id == rfq.id
    assert pr.rfq.product == "bracket"
    # The backref on ReplyRFQExtraction resolves too.
    assert pr in rfq.product_requirements
