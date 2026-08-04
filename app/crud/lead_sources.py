"""CRUD helpers for LeadSource."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.lead_source import LeadSource


def create(db: Session, *, name: str, **kwargs) -> LeadSource:
    obj = LeadSource(name=name, **kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, source_id: int) -> Optional[LeadSource]:
    return db.query(LeadSource).filter(LeadSource.id == source_id).first()


def get_by_name(db: Session, name: str) -> Optional[LeadSource]:
    return db.query(LeadSource).filter(LeadSource.name == name).first()


def list_all(db: Session, *, active_only: bool = False) -> List[LeadSource]:
    q = db.query(LeadSource)
    if active_only:
        q = q.filter(LeadSource.is_active.is_(True))
    return q.order_by(LeadSource.id.desc()).all()


def update(db: Session, obj: LeadSource, **kwargs) -> LeadSource:
    for key, value in kwargs.items():
        if value is not None:
            setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, obj: LeadSource) -> None:
    db.delete(obj)
    db.commit()
