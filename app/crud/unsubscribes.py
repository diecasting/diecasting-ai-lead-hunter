"""CRUD helpers for Unsubscribe."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.unsubscribe import Unsubscribe


def create(db: Session, **kwargs) -> Unsubscribe:
    obj = Unsubscribe(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, unsubscribe_id: int) -> Optional[Unsubscribe]:
    return db.query(Unsubscribe).filter(Unsubscribe.id == unsubscribe_id).first()


def get_by_email(db: Session, email: str) -> Optional[Unsubscribe]:
    return db.query(Unsubscribe).filter(Unsubscribe.email == email).first()


def list_for_lead(db: Session, lead_id: int) -> List[Unsubscribe]:
    return (
        db.query(Unsubscribe)
        .filter(Unsubscribe.lead_id == lead_id)
        .order_by(Unsubscribe.created_at.desc())
        .all()
    )
