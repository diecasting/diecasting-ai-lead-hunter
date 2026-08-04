"""CRUD helpers for Contact."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.contact import Contact


def create(db: Session, *, lead_id: int, **kwargs) -> Contact:
    obj = Contact(lead_id=lead_id, **kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, contact_id: int) -> Optional[Contact]:
    return db.query(Contact).filter(Contact.id == contact_id).first()


def get_by_email(db: Session, email: str) -> Optional[Contact]:
    return db.query(Contact).filter(Contact.email == email).first()


def list_for_lead(db: Session, lead_id: int) -> List[Contact]:
    return (
        db.query(Contact)
        .filter(Contact.lead_id == lead_id)
        .order_by(Contact.id.desc())
        .all()
    )


def update(db: Session, obj: Contact, **kwargs) -> Contact:
    for key, value in kwargs.items():
        if value is not None:
            setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, obj: Contact) -> None:
    db.delete(obj)
    db.commit()
