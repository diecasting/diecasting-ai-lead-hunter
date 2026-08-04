"""CRUD helpers for EmailVerification."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.email_verification import EmailVerification


def create(db: Session, *, email: str, **kwargs) -> EmailVerification:
    obj = EmailVerification(email=email, **kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, verification_id: int) -> Optional[EmailVerification]:
    return db.query(EmailVerification).filter(EmailVerification.id == verification_id).first()


def get_latest_for_email(db: Session, email: str) -> Optional[EmailVerification]:
    return (
        db.query(EmailVerification)
        .filter(EmailVerification.email == email)
        .order_by(EmailVerification.checked_at.desc())
        .first()
    )


def list_for_lead(db: Session, lead_id: int) -> List[EmailVerification]:
    return (
        db.query(EmailVerification)
        .filter(EmailVerification.lead_id == lead_id)
        .order_by(EmailVerification.checked_at.desc())
        .all()
    )
