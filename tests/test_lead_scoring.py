"""Tests for the AI Lead Scoring & Prioritization Engine (Phase 3 Stage 3).

Covers:
  * the five component scorers (unit level)
  * the weighted composite ``lead_score`` + ``priority`` thresholds
  * ``score_lead`` / ``apply_lead_score`` integration with Contacts + Documents
  * regression: lead_score is denormalised onto the ORM row by run_analysis
"""
import json

from app.ai.lead_scoring import (
    HIGH,
    LOW,
    MEDIUM,
    apply_lead_score,
    company_fit_score,
    compute_lead_score,
    contact_quality_score,
    pdf_signal_score,
    procurement_signal_score,
    score_lead,
    score_to_priority,
    website_intent_score,
)
from app.crud import company_documents as doc_crud
from app.crud import contacts as contacts_crud


# ---------------------------------------------------------------------------
# Component: company_fit_score
# ---------------------------------------------------------------------------
class TestCompanyFitScore:
    def test_no_signal(self):
        assert company_fit_score() == 0

    def test_high_casting_manufacturer(self):
        s = company_fit_score(
            casting_need_score=90, business_type="Manufacturer / OEM"
        )
        # base 90 + 25 bonus -> capped 100
        assert s == 100

    def test_medium_cnc_trader(self):
        s = company_fit_score(cnc_need_score=60, business_type="Trader / Distributor")
        # base 60 + 5 bonus = 65
        assert s == 65

    def test_unknown_business_type_no_bonus(self):
        s = company_fit_score(tooling_need_score=70, business_type="Unknown")
        assert s == 70

    def test_primary_score_is_max(self):
        s = company_fit_score(casting_need_score=20, cnc_need_score=85, tooling_need_score=10)
        assert s == 85


# ---------------------------------------------------------------------------
# Component: procurement_signal_score
# ---------------------------------------------------------------------------
class TestProcurementSignalScore:
    def test_none(self):
        assert procurement_signal_score(None) == 0
        assert procurement_signal_score("") == 0

    def test_invalid_json(self):
        assert procurement_signal_score("{not json") == 0

    def test_reads_stored_score(self):
        payload = json.dumps(
            {"procurement_signals": {"score": 72, "type": "casting", "components": {}}}
        )
        assert procurement_signal_score(payload) == 72

    def test_no_procurement_key(self):
        payload = json.dumps({"materials": ["aluminum"]})
        assert procurement_signal_score(payload) == 0


# ---------------------------------------------------------------------------
# Component: website_intent_score
# ---------------------------------------------------------------------------
class TestWebsiteIntentScore:
    def test_high_buying_signal(self):
        assert website_intent_score(buying_signal="HIGH (rfq)") == 100

    def test_medium_buying_signal(self):
        assert website_intent_score(buying_signal="MEDIUM") == 65

    def test_low_buying_signal(self):
        assert website_intent_score(buying_signal="LOW") == 35

    def test_none_signal_default_low(self):
        assert website_intent_score(buying_signal=None) == 10

    def test_procurement_blends_in(self):
        payload = json.dumps(
            {"procurement_signals": {"score": 90, "type": "casting", "components": {}}}
        )
        # procurement*0.9 = 81 > default 10
        assert website_intent_score(buying_signal=None, ai_signals=payload) == 81


# ---------------------------------------------------------------------------
# Component: contact_quality_score
# ---------------------------------------------------------------------------
class TestContactQualityScore:
    def test_no_contacts(self):
        assert contact_quality_score([]) == 0

    def test_single_basic_contact(self):
        class C:
            email = "a@b.com"
            role = None
            title = None
            is_primary = False

        s = contact_quality_score([C()])
        # coverage 10 + email 10 + linkedin bonus (reachable) 5 = 25
        assert s == 25

    def test_full_quality(self):
        class C:
            email = "buyer@acme.com"
            role = "Purchasing Manager"
            title = "Purchasing Manager"
            is_primary = True

        s = contact_quality_score([C(), C(), C()])
        # coverage 30 + email 30 + role 25 + primary 10 + linkedin 5 = 100
        assert s == 100

    def test_with_no_email_no_linkedin(self):
        class C:
            email = None
            role = "CEO"
            title = "CEO"
            is_primary = False

        s = contact_quality_score([C()])
        # coverage 10 + role 15 + linkedin bonus (role present = reachable) 5 = 30
        assert s == 30


# ---------------------------------------------------------------------------
# Component: pdf_signal_score
# ---------------------------------------------------------------------------
class TestPdfSignalScore:
    def test_no_docs(self):
        assert pdf_signal_score([]) == 0

    def test_capability_doc(self):
        class D:
            file_type = "pdf"
            url = "https://acme.com/capability-brochure.pdf"

        assert pdf_signal_score([D()]) == 40

    def test_catalog_doc(self):
        class D:
            file_type = "pdf"
            url = "https://acme.com/product-catalog.pdf"

        assert pdf_signal_score([D()]) == 20

    def test_generic_pdf_baseline(self):
        class D:
            file_type = "pdf"
            url = "https://acme.com/whitepaper.pdf"

        assert pdf_signal_score([D()]) == 10

    def test_multiple_docs_sum_capped(self):
        class D:
            file_type = "pdf"
            url = "https://acme.com/capability.pdf"

        assert pdf_signal_score([D(), D(), D()]) == 100


# ---------------------------------------------------------------------------
# Composite: compute_lead_score + priority
# ---------------------------------------------------------------------------
class TestComputeLeadScore:
    def test_all_zero(self):
        assert compute_lead_score() == 0

    def test_weights_sum_to_one_implicit(self):
        # 50*0.30 + 50*0.20 + 50*0.20 + 50*0.15 + 50*0.15 = 50
        assert compute_lead_score(
            company_fit=50,
            procurement_signal=50,
            website_intent=50,
            contact_quality=50,
            pdf_signal=50,
        ) == 50

    def test_high_composite(self):
        # strong company fit + procurement + intent + contacts + pdf
        s = compute_lead_score(
            company_fit=100, procurement_signal=90, website_intent=100,
            contact_quality=100, pdf_signal=40,
        )
        assert s > 80
        assert s <= 100

    def test_low_composite(self):
        s = compute_lead_score(
            company_fit=0, procurement_signal=0, website_intent=0,
            contact_quality=0, pdf_signal=0,
        )
        assert s == 0


class TestScoreToPriority:
    def test_high_above_80(self):
        assert score_to_priority(81) == HIGH

    def test_high_at_80_is_medium(self):
        # Spec: HIGH > 80 (strictly), so 80 is MEDIUM.
        assert score_to_priority(80) == MEDIUM

    def test_medium_50_to_80(self):
        assert score_to_priority(50) == MEDIUM
        assert score_to_priority(79) == MEDIUM

    def test_low_below_50(self):
        assert score_to_priority(49) == LOW
        assert score_to_priority(0) == LOW


# ---------------------------------------------------------------------------
# Integration: score_lead / apply_lead_score with DB
# ---------------------------------------------------------------------------
class TestScoreLeadIntegration:
    def _make_lead(self, db, **kwargs):
        from app.models.lead import CompanyLead

        lead = CompanyLead(
            name=kwargs.get("name", "ScoreCo"),
            website=kwargs.get("website", "https://score.example.com"),
            casting_need_score=kwargs.get("casting_need_score", 0),
            cnc_need_score=kwargs.get("cnc_need_score", 0),
            tooling_need_score=kwargs.get("tooling_need_score", 0),
            business_type=kwargs.get("business_type"),
            buying_signal=kwargs.get("buying_signal"),
            ai_signals=kwargs.get("ai_signals"),
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead

    def test_score_lead_no_related_data(self, db):
        lead = self._make_lead(
            db,
            name="NoRel",
            casting_need_score=90,
            business_type="Manufacturer / OEM",
            buying_signal="HIGH (rfq)",
        )
        result = score_lead(lead, db=db)
        assert result["lead_score"] > 0
        assert result["priority"] in (HIGH, MEDIUM, LOW)
        assert "company_fit_score" in result["breakdown"]

    def test_score_lead_uses_contacts_and_docs(self, db):
        lead = self._make_lead(
            db,
            name="WithRel",
            casting_need_score=80,
            cnc_need_score=70,
            business_type="Manufacturer / OEM",
        )
        contacts_crud.create(
            db,
            lead_id=lead.id,
            full_name="Jane Buyer",
            email="jane@withrel.com",
            role="Purchasing Manager",
            is_primary=True,
        )
        doc_crud.create(
            db,
            lead_id=lead.id,
            url="https://withrel.com/capability.pdf",
            file_type="pdf",
        )
        result = score_lead(lead, db=db)
        # contact quality + pdf signal should lift the score vs no-data case.
        assert result["breakdown"]["contact_quality_score"] > 0
        assert result["breakdown"]["pdf_signal_score"] == 40
        assert result["lead_score"] > 0

    def test_apply_lead_score_persists(self, db):
        lead = self._make_lead(
            db,
            name="Persist",
            casting_need_score=95,
            business_type="Manufacturer / OEM",
            buying_signal="HIGH (request for quote)",
        )
        result = apply_lead_score(lead, db=db)
        db.refresh(lead)
        assert lead.lead_score == result["lead_score"]
        assert lead.priority == result["priority"]
        assert lead.lead_score_breakdown is not None
        parsed = json.loads(lead.lead_score_breakdown)
        assert "company_fit_score" in parsed

    def test_apply_lead_score_without_db_no_commit(self):
        from app.models.lead import CompanyLead

        lead = CompanyLead(name="NoDb", casting_need_score=100, business_type="Manufacturer / OEM")
        result = apply_lead_score(lead, db=None)
        # Object is mutated but not committed (no DB).
        assert lead.lead_score == result["lead_score"]
        assert lead.priority is not None


# ---------------------------------------------------------------------------
# Regression: run_analysis denormalises lead_score
# ---------------------------------------------------------------------------
class TestRunAnalysisLeadScoreRegression:
    def test_run_analysis_sets_lead_score(self, db):
        from app.ai.analyzer import run_analysis
        from app.models.lead import CompanyLead

        lead = CompanyLead(
            name="Regression Co",
            website="https://regression.example.com",
            description="aluminium die casting automotive EV motor housing manufacturer",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

        run_analysis(db, lead, crawled_text=lead.description or "")

        db.refresh(lead)
        assert lead.lead_score is not None
        assert 0 <= lead.lead_score <= 100
        assert lead.priority in (HIGH, MEDIUM, LOW)
        assert lead.lead_score_breakdown is not None
