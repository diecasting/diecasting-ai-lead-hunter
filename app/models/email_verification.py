"""EmailVerification ORM model (Phase 3 Stage 1).

Stores the result of verifying a contact / lead e-mail address (syntax,
MX, SMTP ping, disposable-domain checks). Links either to a ``contact_id`` or
directly to a ``lead_id`` (when there is no Contact row yet).
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmailVerification(Base):
    """Result of an e-mail deliverability / validity check."""

    __tablename__ = "email_verifications"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)
    status = Column(
        String(20), nullable=False, default="unknown", server_default="unknown", index=True
    )  # valid | invalid | risky | unknown
    is_deliverable = Column(String(10), nullable=True)  # yes | no | unknown
    reason = Column(String(512), nullable=True)
    checked_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmailVerification id={self.id} email={self.email!r} status={self.status!r}>"
