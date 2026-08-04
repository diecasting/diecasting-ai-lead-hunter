"""Contact ORM model (Phase 3 Stage 1).

A ``Contact`` is an individual person at a ``CompanyLead`` company — the human
recipient of outreach (as opposed to the company-level ``contact_email``). This
supports multi-threading an account (e.g. Purchasing + Engineering) and stores
per-contact deliverability / opt-out state.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contact(Base):
    """A person at a lead company who can be contacted directly."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(120), nullable=True)
    role = Column(String(160), nullable=True)          # e.g. Purchasing Manager
    title = Column(String(160), nullable=True)         # free-text job title
    is_primary = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    do_not_contact = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Contact id={self.id} lead_id={self.lead_id} email={self.email!r}>"
