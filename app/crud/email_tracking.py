"""CRUD helpers for EmailTracking.

Each call also bumps the aggregated ``open_count`` / ``click_count`` counter on
the parent ``OutreachMessage`` so reporting does not need to scan every event.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.email_tracking import EmailTracking
from app.models.outreach_message import OutreachMessage


def create(db: Session, *, message_id: int, event_type: str, **kwargs) -> EmailTracking:
    obj = EmailTracking(message_id=message_id, event_type=event_type, **kwargs)
    db.add(obj)
    # Maintain aggregated counters on the parent message.
    message = db.query(OutreachMessage).filter(OutreachMessage.id == message_id).first()
    if message is not None:
        if event_type == "open":
            message.open_count = (message.open_count or 0) + 1
        elif event_type == "click":
            message.click_count = (message.click_count or 0) + 1
        db.add(message)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, tracking_id: int) -> Optional[EmailTracking]:
    return db.query(EmailTracking).filter(EmailTracking.id == tracking_id).first()


def list_for_message(db: Session, message_id: int) -> List[EmailTracking]:
    return (
        db.query(EmailTracking)
        .filter(EmailTracking.message_id == message_id)
        .order_by(EmailTracking.occurred_at.desc())
        .all()
    )


def get_by_token(db: Session, token: str) -> List[EmailTracking]:
    return db.query(EmailTracking).filter(EmailTracking.tracking_token == token).all()
