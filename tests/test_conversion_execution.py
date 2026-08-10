"""Phase 15.3.3: Conversion Recommendation Acceptance -> SalesTask tests.

Verifies :func:`app.conversion.execution.create_task_from_recommendation` and
the ``POST /api/conversion/lead/{id}/accept`` endpoint:

  * prepare_quote / send_capability_case create a SalesTask (no do_not_contact)
  * stop_sequence / suppress_contact set lead.do_not_contact = True
  * duplicate accept returns the existing task (already_exists=True)
  * wrong action -> 409 unless force=True
  * timeline event "task_created" is recorded
  * ConversionService.recompute() never creates a task
"""
import pytest

from app.conversion.execution import create_task_from_recommendation
from app.conversion.service import ConversionService
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.outreach_event import OutreachEvent
from app.models.sales_task import SalesTask


def _make_lead(db, name, do_not_contact=False):
    lead = CompanyLead(name=name, do_not_contact=do_not_contact)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _signal(db, lead_id, *, priority="high", action="prepare_quote", temperature=80, label="hot"):
    sig = ConversionSignal(
        lead_id=lead_id,
        intent_score=60,
        dominant_intent="rfq_request",
        temperature_score=temperature,
        temperature_label=label,
        next_action=action,
        next_action_priority=priority,
        next_action_reason="test seed",
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig


# ---------------------------------------------------------------------------
# 1. prepare_quote creates SalesTask
# ---------------------------------------------------------------------------
def test_prepare_quote_creates_task(db):
    lead = _make_lead(db, "PQ")
    sig = _signal(db, lead.id, action="prepare_quote")

    task, already = create_task_from_recommendation(db, lead, sig, "prepare_quote")
    assert already is False
    assert task.category == "rfq"
    assert task.title == "Prepare quotation"
    assert task.status == "open"
    assert task.company_id == lead.id
    # No opt-out side effect for a positive action.
    assert lead.do_not_contact is False


# ---------------------------------------------------------------------------
# 2. send_capability_case creates SalesTask
# ---------------------------------------------------------------------------
def test_send_capability_case_creates_task(db):
    lead = _make_lead(db, "SC")
    sig = _signal(db, lead.id, action="send_capability_case")

    task, already = create_task_from_recommendation(db, lead, sig, "send_capability_case")
    assert already is False
    assert task.category == "sales"
    assert task.title == "Send capability / value case"
    assert lead.do_not_contact is False


# ---------------------------------------------------------------------------
# 3. stop_sequence updates do_not_contact
# ---------------------------------------------------------------------------
def test_stop_sequence_sets_do_not_contact(db):
    lead = _make_lead(db, "Stop")
    sig = _signal(db, lead.id, action="stop_sequence")

    task, _ = create_task_from_recommendation(db, lead, sig, "stop_sequence")
    assert task.category == "nurture"
    assert task.title == "Stop outreach sequence"
    # Reload to confirm persistence.
    refreshed = db.query(CompanyLead).filter(CompanyLead.id == lead.id).first()
    assert refreshed.do_not_contact is True


# ---------------------------------------------------------------------------
# 4. suppress_contact updates do_not_contact
# ---------------------------------------------------------------------------
def test_suppress_contact_sets_do_not_contact(db):
    lead = _make_lead(db, "Suppress")
    sig = _signal(db, lead.id, action="suppress_contact")

    task, _ = create_task_from_recommendation(db, lead, sig, "suppress_contact")
    assert task.category == "review"
    assert task.title == "Suppress contact (spam)"
    refreshed = db.query(CompanyLead).filter(CompanyLead.id == lead.id).first()
    assert refreshed.do_not_contact is True


# ---------------------------------------------------------------------------
# 5. duplicate accept returns existing task
# ---------------------------------------------------------------------------
def test_duplicate_accept_returns_existing(db):
    lead = _make_lead(db, "Dup")
    sig = _signal(db, lead.id, action="prepare_quote")

    t1, a1 = create_task_from_recommendation(db, lead, sig, "prepare_quote")
    assert a1 is False
    t2, a2 = create_task_from_recommendation(db, lead, sig, "prepare_quote")
    assert a2 is True
    assert t2.id == t1.id
    # Still only one open task for this recommendation.
    count = (
        db.query(SalesTask)
        .filter(SalesTask.company_id == lead.id, SalesTask.category == "rfq")
        .count()
    )
    assert count == 1


# ---------------------------------------------------------------------------
# 6. wrong action returns 409 (via API)
# ---------------------------------------------------------------------------
def test_wrong_action_409(db, client):
    lead = _make_lead(db, "Wrong")
    _signal(db, lead.id, action="prepare_quote")  # recommended action

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "send_capability_case", "force": False},
    )
    assert r.status_code == 409, r.text
    assert "differs from recommended" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 7. force allows override
# ---------------------------------------------------------------------------
def test_force_allows_override(db, client):
    lead = _make_lead(db, "Force")
    _signal(db, lead.id, action="prepare_quote")  # recommended action

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "send_capability_case", "force": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted_action"] == "send_capability_case"
    assert body["category"] == "sales"
    assert body["already_exists"] is False


# ---------------------------------------------------------------------------
# 8. timeline event created
# ---------------------------------------------------------------------------
def test_timeline_event_created(db):
    lead = _make_lead(db, "TL")
    sig = _signal(db, lead.id, action="prepare_quote")

    create_task_from_recommendation(db, lead, sig, "prepare_quote")

    ev = (
        db.query(OutreachEvent)
        .filter(OutreachEvent.lead_id == lead.id, OutreachEvent.event_type == "task_created")
        .first()
    )
    assert ev is not None


# ---------------------------------------------------------------------------
# 9. recompute does NOT create tasks
# ---------------------------------------------------------------------------
def test_recompute_does_not_create_task(db):
    lead = _make_lead(db, "NoAuto")
    # Seed a reply so recompute has something to score (rfq_request -> prepare_quote).
    from app.outreach.reply_ai import analyzer as reply_analyzer

    reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please quote 5000 pcs aluminum die cast housing, ADC12.",
        apply_actions=False,
    )
    # The wiring recomputed the signal; confirm a recommendation exists.
    sig = ConversionService(db).get_signal(lead.id)
    assert sig is not None and sig.next_action == "prepare_quote"

    tasks_before = db.query(SalesTask).filter(SalesTask.company_id == lead.id).count()
    assert tasks_before == 0

    # Explicit recompute must remain task-free.
    ConversionService(db).recompute(lead.id)

    tasks_after = db.query(SalesTask).filter(SalesTask.company_id == lead.id).count()
    assert tasks_after == 0
