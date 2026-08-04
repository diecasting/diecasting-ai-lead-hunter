"""CRUD helpers for OutreachEvent (send / open / reply / bounce tracking)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.outreach_event import OutreachEvent


def create(
    db: Session,
    *,
    lead_id: int,
    event_type: str,
    message_id: Optional[int] = None,
) -> OutreachEvent:
    obj = OutreachEvent(
        lead_id=lead_id,
        message_id=message_id,
        event_type=event_type,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_by_lead(
    db: Session, lead_id: int, *, event_type: Optional[str] = None
) -> List[OutreachEvent]:
    q = db.query(OutreachEvent).filter(OutreachEvent.lead_id == lead_id)
    if event_type:
        q = q.filter(OutreachEvent.event_type == event_type)
    return q.order_by(OutreachEvent.id.desc()).all()


def get_latest_by_lead(
    db: Session, lead_id: int, *, event_type: Optional[str] = None
) -> Optional[OutreachEvent]:
    events = get_by_lead(db, lead_id, event_type=event_type)
    return events[0] if events else None


def count_by_type(db: Session, lead_id: int, event_type: str) -> int:
    return (
        db.query(OutreachEvent)
        .filter(OutreachEvent.lead_id == lead_id, OutreachEvent.event_type == event_type)
        .count()
    )
