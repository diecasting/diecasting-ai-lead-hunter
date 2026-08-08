"""CRM + sales automation triggered by reply intents (Phase 6 + Phase 10).

Phase 6 rules (preserved)::

* ``rfq_request``      → lead status → ``rfq``
* ``interested``       → lead status → ``qualified``
* ``not_interested``   → stop follow-ups + mark do-not-contact
* ``supplier_existing``→ stop the follow-up sequence

All other intents leave the CRM untouched. Status transitions go through the
strict workflow state machine when allowed; when the strict machine rejects
the move (e.g. ``sent -> qualified``), the pipeline stage is forced directly
(re-open semantics) so the automation is robust regardless of where the lead
is in the funnel.

Phase 10 extension::

* For every reply-worthy / actionable intent, a :class:`SalesTask` is created
  so the sales team has a queue of concrete follow-ups.
* For ``rfq_request`` a :class:`ReplyRFQExtraction` is created (deterministic
  parse, optionally upgraded by AI) and any sent ``CampaignContact`` rows for
  the company are advanced to ``rfq``.
* For the remaining genuine replies, any sent ``CampaignContact`` rows are
  advanced to ``replied`` so campaign analytics stay in sync.

The Phase 6 timeline behaviour (``OutreachEvent`` "replied" for genuine
replies) lives in ``analyzer`` and is untouched here.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.campaign import CampaignContact, CC_SENT_STATUSES
from app.models.followup import OutreachFollowUp
from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis
from app.models.reply_rfq_extraction import ReplyRFQExtraction
from app.models.sales_task import (
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_LOW,
    TASK_PRIORITY_MEDIUM,
    TASK_STATUS_OPEN,
    SalesTask,
)

# ---------------------------------------------------------------------------
# Per-intent SalesTask routing.
#
# (category, priority, title, create_task?). Intents that are pure "noise"
# (spam, unknown) or already fully handled by the CRM (not_interested) do not
# spawn a task. ``unknown`` in particular must stay task-free because the Phase
# 6 API contract asserts an ``unknown`` reply yields no applied actions.
# ---------------------------------------------------------------------------
_TASK_POLICY: dict = {
    "rfq_request": ("rfq", TASK_PRIORITY_HIGH, "Prepare quotation for RFQ reply", True),
    "interested": ("sales", TASK_PRIORITY_HIGH, "Follow up on interested reply", True),
    "technical_question": ("sales", TASK_PRIORITY_MEDIUM, "Answer technical question", True),
    "price_request": ("sales", TASK_PRIORITY_MEDIUM, "Send pricing information", True),
    "supplier_existing": ("account", TASK_PRIORITY_LOW, "Log existing supplier; nurture", True),
    "not_interested": ("nurture", TASK_PRIORITY_LOW, None, False),
    "out_of_office": ("follow_up", TASK_PRIORITY_LOW, "Re-engage after out-of-office", True),
    "not_now": ("follow_up", TASK_PRIORITY_MEDIUM, "Re-engage later (not ready)", True),
    "wrong_contact": ("data_quality", TASK_PRIORITY_LOW, "Route to correct contact", True),
    "spam": ("review", TASK_PRIORITY_LOW, None, False),
    "unknown": ("review", TASK_PRIORITY_MEDIUM, None, False),
}

# Intents that represent a genuine customer response and should therefore flip
# any sent campaign-contact queue entries to "replied" (rfq_request is handled
# separately -> "rfq").
_REPLIED_SYNC_INTENTS = {
    "interested",
    "technical_question",
    "price_request",
    "supplier_existing",
    "not_interested",
    "out_of_office",
    "not_now",
    "wrong_contact",
}


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


def _resolve_contact_id(db: Session, lead: CompanyLead, analysis: ReplyAnalysis) -> Optional[int]:
    """Best-effort link from a reply analysis back to a Contact.

    Uses the original outreach message's recipient address (when the analysis
    was produced from a tracked message) matched against the lead's contacts.
    """
    if not analysis.message_id:
        return None
    from app.models.contact import Contact
    from app.models.outreach_message import OutreachMessage

    msg = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.id == analysis.message_id)
        .first()
    )
    if msg is None or not msg.recipient_email:
        return None
    contact = (
        db.query(Contact)
        .filter(
            Contact.lead_id == lead.id,
            Contact.email == msg.recipient_email,
        )
        .first()
    )
    return contact.id if contact else None


def _create_task(
    db: Session,
    *,
    analysis: ReplyAnalysis,
    lead: CompanyLead,
    contact_id: Optional[int],
    category: str,
    priority: str,
    title: str,
) -> SalesTask:
    task = SalesTask(
        reply_id=analysis.id,
        contact_id=contact_id,
        company_id=lead.id,
        title=title,
        description=(
            f"Auto-created from reply intent '{analysis.intent}' "
            f"(analysis #{analysis.id})."
        ),
        priority=priority,
        status=TASK_STATUS_OPEN,
        category=category,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _update_campaign_contacts(db: Session, lead: CompanyLead, *, to_status: str) -> int:
    """Advance any *sent* campaign-contact rows for this company to ``to_status``.

    Returns the number of rows actually transitioned. Campaign counters are
    kept in sync by the campaign CRUD.
    """
    from app.campaign import crud as campaign_crud

    rows = (
        db.query(CampaignContact)
        .filter(
            CampaignContact.company_id == lead.id,
            CampaignContact.status.in_(CC_SENT_STATUSES),
        )
        .all()
    )
    n = 0
    for cc in rows:
        if cc.status == to_status:
            continue
        campaign_crud.update_contact_status(db, cc, to_status)
        n += 1
    return n


def apply_intent_action(
    db: Session, lead: CompanyLead, analysis: ReplyAnalysis
) -> List[str]:
    """Apply the CRM + sales automation for ``analysis.intent``.

    Returns the list of applied actions (Phase 6 status moves plus the Phase 10
    task / RFQ / campaign-sync entries).
    """
    actions: List[str] = []
    intent = analysis.intent
    contact_id = _resolve_contact_id(db, lead, analysis)

    # --- Phase 6 CRM automations (preserved) -------------------------------
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

    # --- Phase 10: SalesTask (per actionable intent) -----------------------
    policy = _TASK_POLICY.get(intent, (None, None, None, False))
    _category, priority, title, make_task = policy
    if make_task and title:
        task = _create_task(
            db,
            analysis=analysis,
            lead=lead,
            contact_id=contact_id,
            category=_category,
            priority=priority,
            title=title,
        )
        actions.append(f"sales_task created: id={task.id}")

    # --- Phase 10: RFQ extraction + campaign sync --------------------------
    if intent == "rfq_request":
        from app.outreach.reply_ai import rfq_extractor

        fields, used_ai = rfq_extractor.extract_rfq(analysis.reply_text, use_ai=True)
        ext = ReplyRFQExtraction(
            analysis_id=analysis.id,
            product=fields.get("product"),
            quantity=fields.get("quantity"),
            material=fields.get("material"),
            process=fields.get("process"),
            deadline=fields.get("deadline"),
            requirements=fields.get("requirements"),
            used_ai=used_ai,
        )
        db.add(ext)
        db.commit()
        db.refresh(ext)
        actions.append(f"rfq_extraction created: id={ext.id} (ai={used_ai})")

        n_cc = _update_campaign_contacts(db, lead, to_status="rfq")
        if n_cc:
            actions.append(f"campaign_contacts -> rfq: {n_cc}")
    elif intent in _REPLIED_SYNC_INTENTS:
        n_cc = _update_campaign_contacts(db, lead, to_status="replied")
        if n_cc:
            actions.append(f"campaign_contacts -> replied: {n_cc}")

    return actions
