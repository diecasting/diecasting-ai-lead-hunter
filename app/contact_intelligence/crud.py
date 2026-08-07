"""Contact Intelligence CRUD (Phase 8.5).

Self-contained helpers for the ``contacts`` table. They deliberately avoid
mutating the existing ``app.crud.contacts`` module so the Phase 3 CRM behaviour
is untouched — these functions only add the intelligence fields
(``source`` / ``title_category`` / ``seniority`` / ``purchasing_score`` /
``priority`` / ``email_address_id`` / ``discovered_at``).
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.contact import (
    SOURCE_WEBSITE,
    Contact,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert(
    db: Session,
    *,
    lead_id: int,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    title: Optional[str] = None,
    source: str = SOURCE_WEBSITE,
    email_address_id: Optional[int] = None,
) -> Contact:
    """Insert or update a contact for a lead, de-duplicated by (lead, email)
    when an e-mail is present, otherwise by (lead, full_name).

    New rows get ``discovered_at`` stamped. Existing rows have their ``title``,
    ``source`` and ``email_address_id`` refreshed (a 'manual' source is never
    downgraded). Returns the (possibly updated) row — classification / scoring
    is applied separately via :func:`set_intelligence`.
    """
    existing = None
    if email:
        existing = (
            db.query(Contact)
            .filter(Contact.lead_id == lead_id, Contact.email == email)
            .first()
        )
    if existing is None and full_name:
        existing = (
            db.query(Contact)
            .filter(Contact.lead_id == lead_id, Contact.full_name == full_name)
            .first()
        )

    if existing is None:
        obj = Contact(
            lead_id=lead_id,
            full_name=full_name,
            email=email,
            title=title,
            source=source,
            email_address_id=email_address_id,
            discovered_at=_utcnow(),
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    # Refresh provenance; never downgrade an explicitly-set 'manual' source.
    if title is not None:
        existing.title = title
    if source and existing.source != "manual":
        existing.source = source
    if email_address_id is not None and existing.email_address_id is None:
        existing.email_address_id = email_address_id
    if email and not existing.email:
        existing.email = email
    if full_name and not existing.full_name:
        existing.full_name = full_name
    db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def set_intelligence(
    db: Session,
    contact: Contact,
    *,
    title_category: str,
    seniority: str,
    purchasing_score: int,
    priority: str,
) -> Contact:
    """Persist the computed title classification + purchasing priority."""
    contact.title_category = title_category
    contact.seniority = seniority
    contact.purchasing_score = purchasing_score
    contact.priority = priority
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def list_for_company(db: Session, company_id: int) -> List[Contact]:
    """All contacts for a company (keyed by ``lead_id`` == company_leads.id)."""
    return (
        db.query(Contact)
        .filter(Contact.lead_id == company_id)
        .order_by(Contact.id.desc())
        .all()
    )


def get(db: Session, contact_id: int) -> Optional[Contact]:
    return db.query(Contact).filter(Contact.id == contact_id).first()


def delete(db: Session, contact_id: int) -> None:
    obj = get(db, contact_id)
    if obj is not None:
        db.delete(obj)
        db.commit()
