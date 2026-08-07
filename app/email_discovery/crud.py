"""Thin CRUD helpers for the :class:`EmailAddress` model (Phase 8)."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.email_address import EmailAddress, VERIFICATION_UNVERIFIED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert(
    db: Session,
    *,
    company_id: Optional[int],
    email: str,
    source: str,
    email_type: str,
    verification_status: Optional[str] = None,
    verification_score: Optional[int] = None,
    verified_at: Optional[datetime] = None,
) -> EmailAddress:
    """Insert or update an :class:`EmailAddress`.

    Uniqueness is on ``(company_id, email)``; ``company_id`` may be ``None``
    (standalone / manually verified addresses). When the row already exists we
    keep it and merely refresh provenance + optional verification results.
    """
    query = db.query(EmailAddress).filter(EmailAddress.email == email)
    if company_id is None:
        query = query.filter(EmailAddress.company_id.is_(None))
    else:
        query = query.filter(EmailAddress.company_id == company_id)
    existing = query.first()

    if existing is None:
        existing = EmailAddress(
            company_id=company_id,
            email=email,
            source=source,
            email_type=email_type,
        )
        db.add(existing)
    else:
        # Prefer the stronger provenance: website/pattern beat nothing, manual
        # always wins. Otherwise keep the earlier source.
        if source == "manual" or existing.source in (None, "", VERIFICATION_UNVERIFIED):
            existing.source = source
        existing.email_type = email_type

    if verification_status is not None:
        existing.verification_status = verification_status
        existing.verification_score = verification_score
        existing.verified_at = verified_at or _utcnow()

    db.flush()
    return existing


def set_verification(db: Session, row: EmailAddress, result) -> EmailAddress:
    """Persist a :class:`EmailVerificationResult` onto ``row``."""
    row.verification_status = result.status
    row.verification_score = result.score
    row.verified_at = _utcnow()
    db.add(row)
    db.flush()
    return row


def list_by_company(db: Session, company_id: int) -> List[EmailAddress]:
    return (
        db.query(EmailAddress)
        .filter(EmailAddress.company_id == company_id)
        .all()
    )


def get(db: Session, email_id: int) -> Optional[EmailAddress]:
    return db.get(EmailAddress, email_id)


def delete(db: Session, email_id: int) -> bool:
    row = get(db, email_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
