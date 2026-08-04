"""Unsubscribe ORM model (Phase 3 Stage 1).

Records an opt-out request (CAN-SPAM / GDPR compliance) so the sender refuses to
e-mail the address again and ``CompanyLead.do_not_contact`` can be derived. One
row per (email / lead) opt-out event; ``reason`` is free-form.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Unsubscribe(Base):
    """A recorded opt-out / unsubscribe request."""

    __tablename__ = "unsubscribes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email = Column(String(255), nullable=True, index=True)
    reason = Column(String(255), nullable=True)
    token = Column(String(128), nullable=True, index=True)  # unsubscribe token
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Unsubscribe id={self.id} email={self.email!r}>"
