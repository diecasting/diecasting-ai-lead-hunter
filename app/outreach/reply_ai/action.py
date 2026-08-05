"""CRM automation triggered by reply intents (Phase 6 Stage 2).

Rules (per the product spec):

* ``rfq_request``      → lead status → ``rfq``
* ``interested``       → lead status → ``qualified``
* ``not_interested``   → stop follow-ups + mark do-not-contact
* ``supplier_existing``→ stop the follow-up sequence

All other intents leave the CRM untouched. Status transitions go through the
strict workflow state machine when allowed; when the strict machine rejects
the move (e.g. ``sent -> qualified``), the pipeline stage is forced directly
(re-open semantics) so the automation is robust regardless of where the lead
is in the funnel.
"""
from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session

from app.models.followup import OutreachFollowUp
from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis


def _set_status(db: Session, lead: CompanyLead, target: str) -> None:
    """Move ``lead`` to ``target``, falling back to a forced set on invalid moves."""
    from app.outreach.workflow import transition as transition_status

    try:
        transition_status(lead, target, db=db)
        return
    except ValueError:
        pass
    lead.lead_status = target
    lead.last_activity_time = datetime.now(timezone.utc)
    db.add(lead)
    db.commit()
    db.refresh(lead)


def _cancel_followups(db: Session, lead: CompanyLead) -> int:
    """Cancel all pending/generated follow-ups for the lead; returns count."""
    rows = (
        db.query(OutreachFollowUp)
        .filter(
            OutreachFollowUp.lead_id == lead.id,
            OutreachFollowUp.status.in_(["pending", "generated"]),
        )
        .all()
    )
    for row in rows:
        row.status = "cancelled"
    if rows:
        db.commit()
    return len(rows)


def apply_intent_action(
    db: Session, lead: CompanyLead, analysis: ReplyAnalysis
) -> List[str]:
    """Apply the CRM automation for ``analysis.intent``; returns applied actions."""
    actions: List[str] = []
    intent = analysis.intent

    if intent == "rfq_request":
        _set_status(db, lead, "rfq")
        actions.append("lead_status -> rfq")
    elif intent == "interested":
        _set_status(db, lead, "qualified")
        actions.append("lead_status -> qualified")
    elif intent == "not_interested":
        n = _cancel_followups(db, lead)
        lead.do_not_contact = True
        db.add(lead)
        db.commit()
        actions.append(f"follow-ups cancelled: {n}")
        actions.append("do_not_contact = true")
    elif intent == "supplier_existing":
        n = _cancel_followups(db, lead)
        actions.append(f"follow-up sequence stopped: {n}")

    return actions
