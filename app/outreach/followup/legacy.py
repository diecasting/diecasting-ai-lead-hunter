"""Follow-up automation — schedule and generate follow-up emails.

Follow-up cadence (days after the initial send):
    Day 0   — first outreach email
    Day 5   — Follow-up 1
    Day 12  — Follow-up 2
    Day 30  — Final follow-up

For each lead that has been contacted (an initial email sent), the module
creates ``outreach_messages`` rows with ``is_followup=True`` and
``followup_seq=1..3`` and sets ``next_followup_date`` on the lead so the
scheduler / sales team knows when to act.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.models.lead import CompanyLead

# Days after the initial send when each follow-up should be sent.
FOLLOWUP_SCHEDULE: List[Dict[str, object]] = [
    {"seq": 1, "day_offset": 5, "label": "Follow-up 1"},
    {"seq": 2, "day_offset": 12, "label": "Follow-up 2"},
    {"seq": 3, "day_offset": 30, "label": "Final follow-up"},
]


def _followup_body(lead: CompanyLead, label: str, original_subject: str) -> str:
    """Generate a short follow-up email body."""
    company = lead.name or "your company"
    return (
        f"Hi {company} Team,\n\n"
        f"I wanted to follow up on my previous email regarding our precision die "
        f"casting and CNC machining services for {company}.\n\n"
        f"If now isn't the right time, I completely understand — but if you're "
        f"evaluating die casting or tooling suppliers for upcoming programs, we'd "
        f"welcome the chance to share our capabilities and a reference list.\n\n"
        f"Best regards,\n"
        f"Die Casting AI Lead Hunter"
    )


def schedule_followups(
    db: Session, lead: CompanyLead, *, base_message_id: Optional[int] = None
) -> List["object"]:
    """Create follow-up message drafts and set ``next_followup_date``.

    Args:
        db: SQLAlchemy session.
        lead: The lead that was just contacted.
        base_message_id: id of the original sent message (for subject context).

    Returns:
        List of created OutreachMessage follow-up rows.
    """
    base_subject = ""
    if base_message_id is not None:
        base = outreach_crud.get(db, base_message_id)
        if base:
            base_subject = base.subject

    created: List["object"] = []
    now = datetime.now(timezone.utc)
    next_date: Optional[datetime] = None

    for spec in FOLLOWUP_SCHEDULE:
        seq = spec["seq"]  # type: ignore[assignment]
        day_offset = spec["day_offset"]  # type: ignore[assignment]
        label = spec["label"]  # type: ignore[assignment]

        due = now + timedelta(days=day_offset)
        subject = f"Re: {base_subject}" if base_subject else f"Follow-up: partnership with {lead.name}"
        body = _followup_body(lead, label, base_subject)

        msg = outreach_crud.create(
            db,
            lead_id=lead.id,
            subject=subject[:500],
            body=body,
            contact_role=None,
            status="draft",
            is_followup=True,
            followup_seq=seq,  # type: ignore[arg-type]
        )
        created.append(msg)
        if next_date is None or due < next_date:
            next_date = due

    # Update lead's next follow-up date.
    if next_date is not None:
        lead.next_followup_date = next_date
        lead.last_activity_time = now
        db.add(lead)
        db.commit()
        db.refresh(lead)

    return created


def get_due_followups(db: Session, *, as_of: Optional[datetime] = None) -> List["object"]:
    """Return follow-up drafts whose lead's ``next_followup_date`` is due.

    Useful for a scheduler job that actually sends the follow-ups when due.
    """
    # Use naive UTC for comparison (SQLite stores naive timestamps).
    as_of = as_of or datetime.utcnow()
    leads = (
        db.query(CompanyLead)
        .filter(
            CompanyLead.next_followup_date.isnot(None),
            CompanyLead.next_followup_date <= as_of,
            CompanyLead.lead_status == "contacted",
        )
        .all()
    )
    result: List["object"] = []
    for lead in leads:
        pending = outreach_crud.get_by_lead(db, lead.id, status="draft")
        for msg in pending:
            if msg.is_followup:
                result.append(msg)
    return result
