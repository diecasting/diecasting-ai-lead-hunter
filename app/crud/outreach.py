"""CRUD helpers for OutreachMessage."""
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
) -> OutreachMessage:
    obj = OutreachMessage(
        lead_id=lead_id,
        subject=subject,
        body=body,
        contact_role=contact_role,
        status=status,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


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


def update_status(db: Session, obj: OutreachMessage, status: str) -> OutreachMessage:
    obj.status = status
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
