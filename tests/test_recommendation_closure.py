"""Phase 15.4.2: Recommendation lifecycle closure tests.

Verifies:
  1. Accepting ``prepare_quote`` creates a SalesTask AND links the accepted
     Recommendation (recommendation.sales_task_id == task.id).
  2. mark_recommendation_completed() closes the recommendation when its task
     is done (status -> completed, completed_at set).
  3. expire_stale_recommendations() expires superseded generated
     recommendations, which are then excluded from "active" queries.
  4. The accept endpoint still works when no generated recommendation exists
     (best-effort, no sales_task_id link required).

Does NOT touch Opportunity creation, Quote logic, the email send path, or
ConversionSignal calculation.
"""
from app.conversion import execution as conv_execution
from app.models.lead import CompanyLead
from app.models.recommendation import (
    REC_ACTIVE_STATUSES,
    REC_STATUS_ACCEPTED,
    REC_STATUS_COMPLETED,
    REC_STATUS_EXPIRED,
    REC_STATUS_GENERATED,
    Recommendation,
)
from app.models.sales_task import SalesTask, TASK_STATUS_DONE, TASK_STATUS_OPEN
from app.outreach.reply_ai import analyzer as reply_analyzer


def _rfq_lead(db):
    """Create a lead + run a real rfq reply so recompute yields prepare_quote."""
    lead = CompanyLead(name="ClosureRfq")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please quote 5000 pcs aluminum die cast housing, ADC12.",
        apply_actions=False,
    )
    return lead


# ---------------------------------------------------------------------------
# 1. accept prepare_quote creates SalesTask and links Recommendation
# ---------------------------------------------------------------------------
def test_accept_prepare_quote_links_sales_task(db, client):
    lead = _rfq_lead(db)

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    task_id = body["task_id"]
    assert task_id is not None

    # A SalesTask was created.
    task = db.query(SalesTask).filter(SalesTask.id == task_id).first()
    assert task is not None
    assert task.conversion_action == "prepare_quote"
    assert task.status == TASK_STATUS_OPEN

    # The accepted Recommendation is linked to that task.
    rec = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == lead.id,
            Recommendation.action == "prepare_quote",
            Recommendation.status == REC_STATUS_ACCEPTED,
        )
        .first()
    )
    assert rec is not None
    assert rec.sales_task_id == task_id


# ---------------------------------------------------------------------------
# 2. completing the task closes the recommendation
# ---------------------------------------------------------------------------
def test_completing_task_closes_recommendation(db, client):
    lead = _rfq_lead(db)

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": False},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]

    rec = (
        db.query(Recommendation)
        .filter(Recommendation.sales_task_id == task_id)
        .first()
    )
    assert rec is not None
    assert rec.status == REC_STATUS_ACCEPTED

    # Simulate the task being closed by the sales team.
    task = db.query(SalesTask).filter(SalesTask.id == task_id).first()
    task.status = TASK_STATUS_DONE
    db.add(task)
    db.commit()

    # Close the recommendation via the lifecycle helper (by task id).
    closed = conv_execution.mark_recommendation_completed(
        db, sales_task_id=task_id
    )
    assert closed is not None
    assert closed.id == rec.id
    assert closed.status == REC_STATUS_COMPLETED
    assert closed.completed_at is not None

    # It is no longer "active".
    still_active = (
        db.query(Recommendation)
        .filter(
            Recommendation.id == rec.id,
            Recommendation.status.in_(REC_ACTIVE_STATUSES),
        )
        .count()
    )
    assert still_active == 0


# ---------------------------------------------------------------------------
# 3. expired recommendation is not returned as active
# ---------------------------------------------------------------------------
def test_expired_recommendation_excluded_from_active(db):
    lead = CompanyLead(name="StaleRecs")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Two generated recommendations for the same (company, action): older + newer.
    old = Recommendation(
        company_id=lead.id,
        action="prepare_quote",
        status=REC_STATUS_GENERATED,
        confidence_score=80.0,
    )
    db.add(old)
    db.commit()
    db.refresh(old)

    new = Recommendation(
        company_id=lead.id,
        action="prepare_quote",
        status=REC_STATUS_GENERATED,
        confidence_score=90.0,
    )
    db.add(new)
    db.commit()
    db.refresh(new)

    # Expire the stale ones (keeps the latest generated per action).
    expired_count = conv_execution.expire_stale_recommendations(
        db, company_id=lead.id
    )
    assert expired_count == 1

    old_after = db.query(Recommendation).filter(Recommendation.id == old.id).first()
    assert old_after.status == REC_STATUS_EXPIRED
    assert old_after.expired_at is not None

    new_after = db.query(Recommendation).filter(Recommendation.id == new.id).first()
    assert new_after.status == REC_STATUS_GENERATED

    # An "active" query (generated + accepted) must not return the expired one.
    active = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == lead.id,
            Recommendation.status.in_(REC_ACTIVE_STATUSES),
        )
        .all()
    )
    active_ids = {a.id for a in active}
    assert old.id not in active_ids
    assert new.id in active_ids


# ---------------------------------------------------------------------------
# 4. accept is best-effort when no generated recommendation exists
# ---------------------------------------------------------------------------
def test_accept_without_generated_recommendation_still_creates_task(db, client):
    """When recompute never ran, accept must still create the task (no rec link)."""
    lead = CompanyLead(name="NoRecAccept")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Seed a minimal signal so the endpoint can read next_action + priority.
    from app.models.conversion_signal import ConversionSignal

    sig = ConversionSignal(
        lead_id=lead.id,
        next_action="prepare_quote",
        next_action_priority="high",
        temperature_score=80,
        temperature_label="hot",
        intent_score=60,
        dominant_intent="rfq_request",
    )
    db.add(sig)
    db.commit()

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": False},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]
    assert task_id is not None

    # No generated recommendation existed, so nothing is linked/accepted.
    linked = (
        db.query(Recommendation)
        .filter(Recommendation.sales_task_id == task_id)
        .count()
    )
    assert linked == 0
