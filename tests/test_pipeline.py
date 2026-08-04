"""Tests for the CRM lead pipeline state machine (workflow.py)."""
import pytest

from app.outreach.workflow import (
    ALL_STATUSES,
    VALID_TRANSITIONS,
    can_transition,
    run_pipeline_for_lead,
    transition,
)


class TestStateMachine:
    """Lead status transitions."""

    def test_valid_transitions_present(self):
        assert "new" in VALID_TRANSITIONS
        assert "contacted" in VALID_TRANSITIONS
        assert "customer" in VALID_TRANSITIONS
        assert "lost" in VALID_TRANSITIONS

    def test_new_to_qualified(self):
        assert can_transition("new", "qualified") is True

    def test_new_to_contacted_invalid(self):
        assert can_transition("new", "contacted") is False

    def test_contacted_to_replied(self):
        assert can_transition("contacted", "replied") is True

    def test_replied_to_customer(self):
        assert can_transition("replied", "customer") is True

    def test_customer_to_lost(self):
        assert can_transition("customer", "lost") is True

    def test_lost_to_new(self):
        assert can_transition("lost", "new") is True

    def test_same_status_allowed(self):
        assert can_transition("contacted", "contacted") is True

    def test_invalid_transition_raises(self, db):
        from app.models.lead import CompanyLead

        lead = CompanyLead(name="SM Test", lead_status="new")
        db.add(lead)
        db.commit()
        db.refresh(lead)
        with pytest.raises(ValueError):
            transition(lead, "contacted", db=db)

    def test_transition_success_persists(self, db):
        from app.models.lead import CompanyLead

        lead = CompanyLead(name="SM2 Test", lead_status="new")
        db.add(lead)
        db.commit()
        db.refresh(lead)
        transition(lead, "qualified", db=db)
        assert lead.lead_status == "qualified"
        assert lead.last_activity_time is not None

    def test_all_statuses_valid(self):
        for s in ALL_STATUSES:
            assert s in VALID_TRANSITIONS or s == "lost"


class TestPipelineIntegration:
    """Full pipeline run via API + workflow."""

    def test_pipeline_new_to_contacted(self, client, db):
        """new HIGH-priority lead → generate email → send → contacted."""
        resp = client.post(
            "/leads",
            json={
                "name": "PipeTest Co",
                "website": "https://pipetest.example.com",
                "industry": "automotive",
                "description": "die casting parts",
                "contact_email": "buyer@pipetest.com",
                "sales_priority": "HIGH",
            },
        )
        lead_id = resp.json()["id"]

        # Set priority and status via PATCH
        client.patch(f"/leads/{lead_id}/status", json={"lead_status": "qualified"})

        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
        report = run_pipeline_for_lead(db, lead, dry_run=True, use_llm=False)
        assert "generated" in report["steps"]
        assert "sent" in report["steps"]
        assert lead.lead_status == "contacted"

    def test_pipeline_skip_if_already_contacted(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "PipeSkip Co",
                "website": "https://pipeskip.example.com",
                "industry": "cnc machining",
                "sales_priority": "HIGH",
                "lead_status": "contacted",
            },
        )
        lead_id = resp.json()["id"]

        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
        report = run_pipeline_for_lead(db, lead, dry_run=True)
        assert any(s.startswith("skip:") for s in report["steps"])
