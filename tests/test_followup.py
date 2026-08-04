"""Tests for the follow-up automation module."""
from datetime import datetime, timedelta, timezone

import pytest

from app.crud import outreach as outreach_crud
from app.outreach.followup import (
    FOLLOWUP_SCHEDULE,
    get_due_followups,
    schedule_followups,
)


class TestFollowupSchedule:
    """Follow-up cadence config."""

    def test_schedule_has_3_steps(self):
        assert len(FOLLOWUP_SCHEDULE) == 3

    def test_day_offsets(self):
        offsets = [s["day_offset"] for s in FOLLOWUP_SCHEDULE]
        assert offsets == [5, 12, 30]

    def test_sequences(self):
        seqs = [s["seq"] for s in FOLLOWUP_SCHEDULE]
        assert seqs == [1, 2, 3]


class TestScheduleFollowups:
    """generate follow-up messages for a lead."""

    def test_schedule_creates_3_followups(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "FollowTest Co",
                "website": "https://followtest.example.com",
                "industry": "hydraulic",
                "contact_email": "eng@followtest.com",
            },
        )
        lead_id = resp.json()["id"]

        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
        created = schedule_followups(db, lead, base_message_id=None)
        assert len(created) == 3
        for msg in created:
            assert msg.is_followup is True
            assert msg.status == "draft"
        # next_followup_date should be set to Day 5 (earliest)
        assert lead.next_followup_date is not None
        # SQLite stores naive UTC; compare against naive now + 5 days
        from datetime import datetime as _dt

        expected = _dt.utcnow() + timedelta(days=5)
        diff = abs((lead.next_followup_date - expected).total_seconds())
        assert diff < 120

    def test_followups_linked_to_lead(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "FollowLink Co",
                "website": "https://followlink.example.com",
                "industry": "pump",
                "contact_email": "x@followlink.com",
            },
        )
        lead_id = resp.json()["id"]

        msgs = outreach_crud.get_by_lead(db, lead_id)
        assert len(msgs) == 0  # nothing yet

        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
        schedule_followups(db, lead)
        msgs = outreach_crud.get_by_lead(db, lead_id)
        followups = [m for m in msgs if m.is_followup]
        assert len(followups) == 3


class TestDueFollowups:
    """get_due_followups returns follow-ups whose date is past."""

    def test_due_followups(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "DueTest Co",
                "website": "https://duetest.example.com",
                "industry": "gearbox",
                "contact_email": "x@duetest.com",
                "lead_status": "contacted",
            },
        )
        lead_id = resp.json()["id"]

        from app.models.lead import CompanyLead

        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
        # Set next_followup_date in the past (naive UTC, as SQLite stores it)
        from datetime import datetime as _dt

        lead.next_followup_date = _dt.utcnow() - timedelta(days=1)
        db.add(lead)
        db.commit()

        # Create follow-up draft messages directly (without schedule_followups,
        # which would overwrite next_followup_date with a future date).
        from app.crud import outreach as oc

        oc.create(
            db, lead_id=lead_id, subject="Follow-up 1", body="...",
            status="draft", is_followup=True, followup_seq=1,
        )
        due = get_due_followups(db)
        assert len(due) >= 1
        assert all(m.is_followup for m in due)
