"""Phase 15.4.1: Recommendation Lifecycle foundation tests.

Verifies that ConversionService.recompute() records a ``generated``
Recommendation for the lead's next action, that the Phase 15.3.3 accept
endpoint flips the latest generated Recommendation to ``accepted``, and that
recompute never creates a SalesTask.
"""
from app.conversion.service import ConversionService
from app.models.lead import CompanyLead
from app.models.recommendation import (
    REC_STATUS_ACCEPTED,
    REC_STATUS_GENERATED,
    Recommendation,
)
from app.models.sales_task import SalesTask
from app.outreach.reply_ai import analyzer as reply_analyzer


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _rfq_lead(db):
    """Create a lead and run a real rfq reply so recompute yields prepare_quote."""
    lead = _make_lead(db, "RecRfq")
    reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please quote 5000 pcs aluminum die cast housing, ADC12.",
        apply_actions=False,
    )
    return lead


# ---------------------------------------------------------------------------
# 1. recompute creates a generated Recommendation
# ---------------------------------------------------------------------------
def test_recompute_creates_recommendation(db):
    lead = _rfq_lead(db)

    recs = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == lead.id)
        .order_by(Recommendation.id.desc())
        .all()
    )
    assert len(recs) >= 1
    latest = recs[0]
    assert latest.status == REC_STATUS_GENERATED
    assert latest.action == "prepare_quote"
    assert latest.conversion_signal_id is not None
    # confidence_score derived from priority (high -> 100)
    assert latest.confidence_score == 100.0


# ---------------------------------------------------------------------------
# 2. accept changes Recommendation status to accepted
# ---------------------------------------------------------------------------
def test_accept_marks_recommendation_accepted(db, client):
    lead = _rfq_lead(db)

    # Sanity: a generated recommendation exists.
    before = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == lead.id,
            Recommendation.action == "prepare_quote",
            Recommendation.status == REC_STATUS_GENERATED,
        )
        .count()
    )
    assert before >= 1

    r = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": False},
    )
    assert r.status_code == 200, r.text

    accepted = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == lead.id,
            Recommendation.action == "prepare_quote",
            Recommendation.status == REC_STATUS_ACCEPTED,
        )
        .all()
    )
    assert len(accepted) == 1
    assert accepted[0].accepted_at is not None


# ---------------------------------------------------------------------------
# 3. recompute does NOT create a SalesTask
# ---------------------------------------------------------------------------
def test_recompute_does_not_create_sales_task(db):
    lead = _rfq_lead(db)

    tasks_before = (
        db.query(SalesTask).filter(SalesTask.company_id == lead.id).count()
    )
    # The reply flow (apply_actions=False) created no task; recompute must not.
    assert tasks_before == 0

    ConversionService(db).recompute(lead.id)

    tasks_after = (
        db.query(SalesTask).filter(SalesTask.company_id == lead.id).count()
    )
    assert tasks_after == 0


# ---------------------------------------------------------------------------
# 4. re-recompute creates a new generated recommendation (latest wins)
# ---------------------------------------------------------------------------
def test_recompute_creates_fresh_recommendation_each_time(db):
    lead = _rfq_lead(db)

    count1 = (
        db.query(Recommendation).filter(Recommendation.company_id == lead.id).count()
    )
    assert count1 >= 1

    ConversionService(db).recompute(lead.id)

    count2 = (
        db.query(Recommendation).filter(Recommendation.company_id == lead.id).count()
    )
    assert count2 == count1 + 1
    # The newest one is generated and is what accept will pick up.
    newest = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == lead.id)
        .order_by(Recommendation.id.desc())
        .first()
    )
    assert newest.status == REC_STATUS_GENERATED
