"""Follow-up scheduling and due-processing engine (Phase 6 Stage 1).

Automation rules:
  * after an initial email is sent, :func:`schedule_for_lead` creates the
    follow-up schedule rows (``OutreachFollowUp``) from the lead's sequence.
  * before a due follow-up is sent, the lead status is checked; if the lead
    replied / converted (replied, rfq, customer, closed) the follow-up is
    cancelled.
  * :func:`process_due_followups` generates each due follow-up (draft
    ``OutreachMessage``) and sends it through the configured email provider.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.crud import outreach as outreach_crud
from app.models.followup import OutreachFollowUp
from app.models.lead import CompanyLead
from app.outreach.sender import get_email_sender

from app.outreach.followup import generator, sequence as sequence_module

# Lead statuses that stop the follow-up automation.
STOP_STATUSES = {"replied", "rfq", "customer", "closed"}


def lead_stopped(lead: CompanyLead) -> bool:
    """True when the lead replied / converted / closed — no more follow-ups."""
    return (lead.lead_status or "") in STOP_STATUSES


def schedule_for_lead(
    db: Session,
    lead: CompanyLead,
    original_message=None,
    *,
    sequence_id: Optional[int] = None,
    scheduled_from: Optional[datetime] = None,
) -> List[OutreachFollowUp]:
    """Create the follow-up schedule after an initial email is sent.

    Idempotent: if pending/generated follow-ups already exist for this
    (lead, original_message) pair, nothing new is created.
    """
    if original_message is not None:
        existing = (
            db.query(OutreachFollowUp)
            .filter(
                OutreachFollowUp.lead_id == lead.id,
                OutreachFollowUp.original_message_id == original_message.id,
                OutreachFollowUp.status.in_(["pending", "generated"]),
            )
            .all()
        )
        if existing:
            if sequence_id is not None:
                # Explicit sequence override: cancel the old pending rows and
                # re-schedule with the requested sequence.
                for row in existing:
                    row.status = "cancelled"
                db.commit()
            else:
                return []

    seq = None
    if sequence_id is not None:
        seq = sequence_module.get_sequence(db, sequence_id)
    elif original_message is not None or lead.lead_status:
        seq = sequence_module.default_sequence(db)
    steps = seq.steps_list() if seq else sequence_module.DEFAULT_STEPS

    base = scheduled_from or datetime.now(timezone.utc)
    created: List[OutreachFollowUp] = []
    for i, step in enumerate(steps, start=1):
        row = OutreachFollowUp(
            lead_id=lead.id,
            original_message_id=original_message.id if original_message else None,
            sequence_id=seq.id if seq else None,
            step_number=i,
            scheduled_at=base + timedelta(days=int(step["delay_days"])),
            status="pending",
        )
        db.add(row)
        db.flush()
        created.append(row)
    db.commit()
    return created


def list_followups(
    db: Session, *, status: Optional[str] = None, lead_id: Optional[int] = None
) -> List[OutreachFollowUp]:
    q = db.query(OutreachFollowUp)
    if status:
        q = q.filter(OutreachFollowUp.status == status)
    if lead_id is not None:
        q = q.filter(OutreachFollowUp.lead_id == lead_id)
    return q.order_by(OutreachFollowUp.scheduled_at).all()


def get_followup(db: Session, followup_id: int) -> Optional[OutreachFollowUp]:
    return (
        db.query(OutreachFollowUp)
        .filter(OutreachFollowUp.id == followup_id)
        .first()
    )


def set_status(
    db: Session, followup: OutreachFollowUp, status: str
) -> OutreachFollowUp:
    followup.status = status
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


def _step_for(followup: OutreachFollowUp) -> dict:
    if followup.sequence is not None:
        steps = followup.sequence.steps_list()
        if 0 <= followup.step_number - 1 < len(steps):
            return steps[followup.step_number - 1]
    steps = sequence_module.DEFAULT_STEPS
    if 0 <= followup.step_number - 1 < len(steps):
        return steps[followup.step_number - 1]
    return {"delay_days": 3, "template": "technical_followup"}


def process_due_followups(
    db: Session, *, now: Optional[datetime] = None, sender=None, use_llm: bool = False
) -> dict:
    """Generate + send every due follow-up, guarding the lead status.

    Returns a summary dict with processed / generated / sent / cancelled /
    skipped / send_failed counts. A follow-up with no recipient stays
    ``generated`` (retried on the next tick once a contact exists).
    """
    # SQLite stores naive datetimes; compare against a naive cutoff.
    cutoff = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    due = (
        db.query(OutreachFollowUp)
        .filter(
            OutreachFollowUp.status.in_(["pending", "generated"]),
            OutreachFollowUp.scheduled_at <= cutoff,
        )
        .order_by(OutreachFollowUp.scheduled_at)
        .all()
    )

    summary = {
        "processed": 0,
        "generated": 0,
        "sent": 0,
        "cancelled": 0,
        "skipped_no_recipient": 0,
        "send_failed": 0,
    }

    for fu in due:
        lead = fu.lead
        # Stop rule: lead replied / converted / closed.
        if lead_stopped(lead):
            fu.status = "cancelled"
            db.add(fu)
            db.commit()
            summary["cancelled"] += 1
            continue

        # Generate the follow-up draft on first due pass.
        if fu.status == "pending":
            try:
                msg = generator.generate_followup_email(
                    db,
                    lead,
                    fu.original_message,
                    step=_step_for(fu),
                    step_number=fu.step_number,
                )
            except Exception:
                # Per-item isolation: leave pending, retry next tick.
                continue
            fu.message_id = msg.id
            fu.status = "generated"
            db.add(fu)
            db.commit()
            summary["generated"] += 1
        else:
            msg = fu.message

        recipient = ""
        if msg is not None:
            recipient = (msg.recipient_email or "").strip()
        if not recipient:
            recipient = (lead.contact_email or "").strip()
        if not recipient:
            summary["skipped_no_recipient"] += 1
            continue

        provider = sender or get_email_sender()
        if provider.validate_recipient(recipient):
            summary["skipped_no_recipient"] += 1
            continue

        receipt = provider.send_email(
            subject=msg.subject,
            body=msg.body,
            recipient=recipient,
            sender=provider.from_email or None,
        )
        if receipt.success:
            outreach_crud.mark_sent(
                db, msg, sender=receipt.sender, recipient=recipient
            )
            fu.status = "sent"
            db.add(fu)
            db.commit()
            summary["sent"] += 1
        else:
            summary["send_failed"] += 1
        summary["processed"] += 1

    return summary
