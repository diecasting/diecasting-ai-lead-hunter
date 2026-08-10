"""Phase 15.3.5: Conversion Task Deduplication integration test.

End-to-end check that a Phase 10 reply-driven task and a Phase 15.3.3
accept-driven task for the same recommendation collapse into a single open
SalesTask (keyed on company_id + conversion_action + status=open).

Flow under test:
  customer reply (rfq_request)
    -> ReplyAnalysis
    -> reply_ai.action.apply_intent_action (creates reply-driven task, tagged prepare_quote)
    -> ConversionSignal (via 15.2.1 recompute wiring)
    -> POST /api/conversion/lead/{id}/accept {action: prepare_quote}
    => assert exactly ONE open SalesTask with conversion_action=prepare_quote
"""
from app.models.lead import CompanyLead
from app.models.sales_task import SalesTask, TASK_STATUS_OPEN
from app.outreach.reply_ai import analyzer as reply_analyzer


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_reply_then_accept_collapses_to_single_open_task(db, client):
    lead = _make_lead(db, "DedupRfq")

    # 1) Customer reply -> ReplyAnalysis + CRM automation + recompute.
    analysis, actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please quote 5000 pcs aluminum die cast housing, ADC12.",
        apply_actions=True,
    )
    assert analysis.intent == "rfq_request"

    # Reply-driven task must now exist and be tagged for de-duplication.
    reply_tasks = (
        db.query(SalesTask)
        .filter(
            SalesTask.company_id == lead.id,
            SalesTask.conversion_action == "prepare_quote",
            SalesTask.status == TASK_STATUS_OPEN,
        )
        .all()
    )
    assert len(reply_tasks) == 1, "reply flow should tag exactly one prepare_quote task"

    # 2) ConversionSignal must be present (from recompute wiring).
    r = client.get(f"/api/conversion/lead/{lead.id}")
    assert r.status_code == 200, r.text
    assert r.json()["next_action"] == "prepare_quote"

    # 3) Human accepts the recommendation.
    acc = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": False},
    )
    assert acc.status_code == 200, acc.text
    body = acc.json()
    assert body["accepted_action"] == "prepare_quote"
    # The accept endpoint should have reused the reply-driven task.
    assert body["already_exists"] is True

    # 4) Exactly ONE open prepare_quote task for this lead.
    open_tasks = (
        db.query(SalesTask)
        .filter(
            SalesTask.company_id == lead.id,
            SalesTask.conversion_action == "prepare_quote",
            SalesTask.status == TASK_STATUS_OPEN,
        )
        .all()
    )
    assert len(open_tasks) == 1, (
        f"expected 1 open prepare_quote task, found {len(open_tasks)}"
    )


def test_accept_without_prior_reply_creates_single_task(db, client):
    """When there is no reply-driven task, accept creates exactly one."""
    lead = _make_lead(db, "NoReplyAccept")

    # Seed a signal without going through the reply flow.
    from app.conversion.service import ConversionService

    ConversionService(db).recompute(lead.id)

    acc = client.post(
        f"/api/conversion/lead/{lead.id}/accept",
        json={"action": "prepare_quote", "force": True},
    )
    assert acc.status_code == 200, acc.text

    open_tasks = (
        db.query(SalesTask)
        .filter(
            SalesTask.company_id == lead.id,
            SalesTask.conversion_action == "prepare_quote",
            SalesTask.status == TASK_STATUS_OPEN,
        )
        .all()
    )
    assert len(open_tasks) == 1
