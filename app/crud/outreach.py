"""CRUD helpers for OutreachMessage."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.outreach_message import OutreachMessage


def create(
    db: Session,
    *,
    lead_id: int,
    subject: str,
    body: str,
    contact_role: Optional[str] = None,
    status: str = "draft",
    is_followup: bool = False,
    followup_seq: int = 0,
    quality_score: Optional[int] = None,
) -> OutreachMessage:
    obj = OutreachMessage(
        lead_id=lead_id,
        subject=subject,
        body=body,
        contact_role=contact_role,
        status=status,
        is_followup=is_followup,
        followup_seq=followup_seq,
        quality_score=quality_score,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, message_id: int) -> Optional[OutreachMessage]:
    return db.query(OutreachMessage).filter(OutreachMessage.id == message_id).first()


def get_by_lead(
    db: Session, lead_id: int, *, status: Optional[str] = None
) -> List[OutreachMessage]:
    q = db.query(OutreachMessage).filter(OutreachMessage.lead_id == lead_id)
    if status:
        q = q.filter(OutreachMessage.status == status)
    return q.order_by(OutreachMessage.id.desc()).all()


def list_drafts(
    db: Session, *, skip: int = 0, limit: int = 50
) -> List[OutreachMessage]:
    return (
        db.query(OutreachMessage)
        .filter(OutreachMessage.status == "draft")
        .order_by(OutreachMessage.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def list_sent(db: Session, *, lead_id: Optional[int] = None) -> List[OutreachMessage]:
    q = db.query(OutreachMessage).filter(OutreachMessage.status == "sent")
    if lead_id is not None:
        q = q.filter(OutreachMessage.lead_id == lead_id)
    return q.order_by(OutreachMessage.sent_time.desc().nullslast()).all()


def update_status(
    db: Session, obj: OutreachMessage, status: str
) -> OutreachMessage:
    obj.status = status
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_sent(
    db: Session,
    obj: OutreachMessage,
    *,
    sender: str = "",
    recipient: str = "",
    sent_time: Optional[datetime] = None,
) -> OutreachMessage:
    obj.status = "sent"
    obj.sent_time = sent_time or datetime.now(timezone.utc)
    obj.sender = sender
    obj.recipient = recipient
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def count_followups(db: Session, lead_id: int) -> int:
    return (
        db.query(OutreachMessage)
        .filter(OutreachMessage.lead_id == lead_id, OutreachMessage.is_followup.is_(True))
        .count()
    )
