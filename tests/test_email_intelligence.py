"""Email Verification Intelligence Layer tests (Phase 4 Stage 1).

Covers the four required areas:
  * multi-contact selection (role-priority strategy)
  * email confidence scoring
  * API verifier mock (ApiEmailVerifier / MockApiEmailVerifier)
  * outreach routing (best contact auto-selected before send)
"""
from app.outreach.api_verifier import ApiEmailVerifier, MockApiEmailVerifier
from app.outreach.confidence import confidence_label, score_email_confidence
from app.outreach.contact_selector import (
    rank_contacts,
    role_priority,
    select_best_contact,
)
from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    VerificationResult,
)
from app.outreach.quality_gate import EmailQualityGate
from app.outreach.workflow import select_outreach_contact


# ---------------------------------------------------------------------------
# API verifier mock
# ---------------------------------------------------------------------------
class TestApiVerifierMock:
    def test_mock_returns_fixed_valid(self):
        v = MockApiEmailVerifier(fixed_response={"status": "valid", "score": 97})
        r = v.verify("buyer@acme.com")
        assert r.status == VALID
        assert r.score == 97

    def test_mock_responder_per_email(self):
        def responder(email):
            return {"status": "invalid" if "bad" in email else "valid"}

        v = MockApiEmailVerifier(responder=responder)
        assert v.verify("bad@x.com").status == INVALID
        assert v.verify("good@x.com").status == VALID

    def test_api_verifier_maps_provider_tokens(self):
        # A subclass that just returns canned JSON (no network).
        class FakeZeroBounce(ApiEmailVerifier):
            def api_call(self, email):
                return {
                    "status": "valid",
                    "sub_status": "antispam_system",
                    "score": "98",
                }

        v = FakeZeroBounce(api_key="k")
        r = v.verify("buyer@acme.com")
        assert r.status == VALID
        assert r.score == 98

    def test_api_verifier_maps_accept_all_to_risky(self):
        class Fake(ApiEmailVerifier):
            def api_call(self, email):
                return {"status": "accept_all", "score": 40}

        v = Fake()
        r = v.verify("info@acme.com")
        assert r.status == RISKY

    def test_api_verifier_handles_error_as_unknown(self):
        class Fake(ApiEmailVerifier):
            def api_call(self, email):
                raise RuntimeError("timeout")

        v = Fake()
        r = v.verify("x@y.com")
        assert r.status == UNKNOWN

    def test_abstract_api_verifier_cannot_be_instantiated(self):
        import pytest

        # api_call is abstract -> the class cannot be instantiated directly.
        with pytest.raises(TypeError):
            ApiEmailVerifier()


# ---------------------------------------------------------------------------
# Email confidence scoring
# ---------------------------------------------------------------------------
class TestConfidenceScoring:
    def test_valid_high_role_confident(self):
        vr = VerificationResult(status=VALID, score=95)
        s = score_email_confidence("a@b.com", vr, role="Purchasing Manager", has_email=True)
        assert s >= 90
        assert confidence_label(s) == "high"

    def test_risky_lowers_confidence(self):
        vr = VerificationResult(status=RISKY, score=20)
        s = score_email_confidence("a@b.com", vr, role="info", has_email=True)
        assert s < 50
        assert confidence_label(s) in ("very_low", "low")

    def test_invalid_floors_zero(self):
        vr = VerificationResult(status=INVALID, score=0)
        s = score_email_confidence("a@b.com", vr, has_email=True)
        assert s == 0

    def test_do_not_contact_zero(self):
        vr = VerificationResult(status=VALID, score=100)
        s = score_email_confidence("a@b.com", vr, do_not_contact=True)
        assert s == 0

    def test_unknown_medium_low(self):
        vr = VerificationResult(status=UNKNOWN, score=50)
        s = score_email_confidence("a@b.com", vr, role="Engineering Manager", has_email=True)
        assert 40 <= s < 80

    def test_primary_bonus(self):
        vr = VerificationResult(status=VALID, score=80)
        a = score_email_confidence("a@b.com", vr, role="Buyer", has_email=True, is_primary=False)
        b = score_email_confidence("a@b.com", vr, role="Buyer", has_email=True, is_primary=True)
        assert b > a

    def test_role_bonus_ordering(self):
        vr = VerificationResult(status=VALID, score=80)
        purchasing = score_email_confidence("a@b.com", vr, role="Purchasing Manager")
        engineering = score_email_confidence("a@b.com", vr, role="Engineering Manager")
        assert purchasing > engineering


# ---------------------------------------------------------------------------
# Multi-contact selection (role-priority strategy)
# ---------------------------------------------------------------------------
class _Contact:
    def __init__(self, email, role=None, primary=False, dnc=False):
        self.email = email
        self.role = role
        self.title = role
        self.is_primary = primary
        self.do_not_contact = dnc
        self.id = id(self)


class TestContactSelection:
    def test_purchasing_beats_engineering(self):
        contacts = [
            _Contact("eng@acme.com", "Engineering Manager"),
            _Contact("pur@acme.com", "Purchasing Manager"),
        ]
        best = select_best_contact(contacts)
        assert best.email == "pur@acme.com"

    def test_role_priority_ordering(self):
        # Purchasing > Strategic Sourcing > Supplier Quality > Engineering
        contacts = [
            _Contact("eng@acme.com", "Engineering Manager"),
            _Contact("sq@acme.com", "Supplier Quality"),
            _Contact("src@acme.com", "Strategic Sourcing Manager"),
            _Contact("pur@acme.com", "Purchasing Manager"),
        ]
        ranked = [c.email for c in rank_contacts(contacts)]
        assert ranked == ["pur@acme.com", "src@acme.com", "sq@acme.com", "eng@acme.com"]

    def test_do_not_contact_excluded(self):
        contacts = [
            _Contact("pur@acme.com", "Purchasing Manager"),
            _Contact("src@acme.com", "Strategic Sourcing Manager", dnc=True),
        ]
        best = select_best_contact(contacts)
        assert best.email == "pur@acme.com"

    def test_no_email_excluded(self):
        contacts = [_Contact(None, "Purchasing Manager")]
        assert select_best_contact(contacts) is None

    def test_empty_returns_none(self):
        assert select_best_contact([]) is None

    def test_primary_breaks_tie(self):
        contacts = [
            _Contact("a@acme.com", "Engineering Manager", primary=False),
            _Contact("b@acme.com", "Engineering Manager", primary=True),
        ]
        best = select_best_contact(contacts)
        assert best.email == "b@acme.com"

    def test_unknown_role_ranked_last(self):
        contacts = [
            _Contact("unk@acme.com", "Intern"),
            _Contact("pur@acme.com", "Purchasing Manager"),
        ]
        best = select_best_contact(contacts)
        assert best.email == "pur@acme.com"

    def test_role_priority_values(self):
        assert role_priority("Purchasing Manager") < role_priority("Strategic Sourcing")
        assert role_priority("Strategic Sourcing") < role_priority("Supplier Quality")
        assert role_priority("Supplier Quality") < role_priority("Engineering Manager")


# ---------------------------------------------------------------------------
# Outreach routing (best contact auto-selected before send)
# ---------------------------------------------------------------------------
class TestOutreachRouting:
    def _make_lead_with_contacts(self, client, db, contacts):
        """Create a lead, then insert Contact rows for it directly via CRUD."""
        resp = client.post(
            "/leads",
            json={
                "name": "Route Co",
                "website": "https://route.example.com",
                "contact_email": "company@route.example.com",
            },
        )
        lead_id = resp.json()["id"]
        from app.crud import contacts as contacts_crud

        for c in contacts:
            contacts_crud.create(
                db,
                lead_id=lead_id,
                full_name=c.get("full_name", "X"),
                email=c["email"],
                role=c.get("role"),
                is_primary=c.get("is_primary", False),
                do_not_contact=c.get("do_not_contact", False),
            )
        return lead_id

    def test_select_outreach_contact_picks_purchasing(self, client, db):
        from app.crud import contacts as contacts_crud

        lead_id = self._make_lead_with_contacts(
            client, db,
            [
                {"email": "eng@route.example.com", "role": "Engineering Manager"},
                {"email": "pur@route.example.com", "role": "Purchasing Manager", "is_primary": True},
            ],
        )
        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter_by(id=lead_id).first()
        gate = EmailQualityGate()
        chosen = select_outreach_contact(db, lead, gate=gate)
        assert chosen is not None
        assert chosen.email == "pur@route.example.com"

    def test_routing_skips_do_not_contact(self, client, db):
        from app.crud import contacts as contacts_crud
        from app.models.lead import CompanyLead

        lead_id = self._make_lead_with_contacts(
            client, db,
            [
                {"email": "pur@route.example.com", "role": "Purchasing Manager", "do_not_contact": True},
                {"email": "src@route.example.com", "role": "Strategic Sourcing Manager"},
            ],
        )
        lead = db.query(CompanyLead).filter_by(id=lead_id).first()
        chosen = select_outreach_contact(db, lead, gate=EmailQualityGate())
        assert chosen.email == "src@route.example.com"

    def test_pipeline_uses_selected_contact_when_present(self, client, db, monkeypatch):
        """run_pipeline_for_lead should route to the best extracted contact."""
        from app import config as config_mod
        from app.crud import contacts as contacts_crud
        from app.outreach.workflow import run_pipeline_for_lead

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = self._make_lead_with_contacts(
            client, db,
            [
                {"email": "eng@route.example.com", "role": "Engineering Manager"},
                {"email": "pur@route.example.com", "role": "Purchasing Manager"},
            ],
        )
        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter_by(id=lead_id).first()
        # Force HIGH priority so the daily pipeline would pick it up.
        lead.sales_priority = "HIGH"
        lead.lead_status = "new"
        db.add(lead)
        db.commit()

        report = run_pipeline_for_lead(
            db, lead, dry_run=True, gate=EmailQualityGate()
        )
        assert "sent" in report["steps"]
        assert report.get("selected_contact_id") is not None
        chosen = contacts_crud.get(db, report["selected_contact_id"])
        assert chosen.email == "pur@route.example.com"

    def test_routing_falls_back_to_company_email(self, client, db, monkeypatch):
        from app import config as config_mod
        from app.outreach.workflow import run_pipeline_for_lead

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        # Lead with no extracted contacts -> use company contact_email.
        resp = client.post(
            "/leads",
            json={
                "name": "NoContactRoute Co",
                "website": "https://noroute.example.com",
                "contact_email": "company@noroute.example.com",
                "sales_priority": "HIGH",
                "lead_status": "new",
            },
        )
        lead_id = resp.json()["id"]
        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter_by(id=lead_id).first()
        report = run_pipeline_for_lead(
            db, lead, dry_run=True, gate=EmailQualityGate()
        )
        assert "sent" in report["steps"]
        assert report.get("selected_contact_id") is None
