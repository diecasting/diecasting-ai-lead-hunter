"""CRUD helpers for ReplyInbox."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.reply_inbox import ReplyInbox


def create(db: Session, **kwargs) -> ReplyInbox:
    obj = ReplyInbox(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, reply_id: int) -> Optional[ReplyInbox]:
    return db.query(ReplyInbox).filter(ReplyInbox.id == reply_id).first()


def list_all(db: Session, *, bounces_only: bool = False) -> List[ReplyInbox]:
    q = db.query(ReplyInbox)
    if bounces_only:
        q = q.filter(ReplyInbox.is_bounce.is_(True))
    return q.order_by(ReplyInbox.received_at.desc()).all()


def list_for_lead(db: Session, lead_id: int) -> List[ReplyInbox]:
    return (
        db.query(ReplyInbox)
        .filter(ReplyInbox.lead_id == lead_id)
        .order_by(ReplyInbox.received_at.desc())
        .all()
    )
