"""IncomingEmail ORM model — Phase 6 Stage 3.

One row per inbound customer email pulled from the reply inbox (IMAP) by the
inbox connector. ``processed`` marks whether it has been through the reply
intelligence pipeline; matched emails get ``matched_lead_id`` /
``message_id`` (the originating outreach message) and ``analysis_id`` (the
created :class:`ReplyAnalysis`). Unmatched emails stay ``processed=False`` so
an operator can review them.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IncomingEmail(Base):
    """An inbound reply fetched from the email inbox."""

    __tablename__ = "incoming_emails"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), nullable=True, index=True)  # IMAP uid/seq
    sender_email = Column(String(255), nullable=False, index=True)
    sender_name = Column(String(255), nullable=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False, index=True)
    processed = Column(
        Boolean,
        nullable=False, default=False, server_default="0", index=True,
    )
    matched_lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    analysis_id = Column(
        Integer,
        ForeignKey("reply_analyses.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="incoming_emails", lazy="selectin")
    message = relationship(
        "OutreachMessage", backref="incoming_emails", lazy="selectin"
    )
    analysis = relationship("ReplyAnalysis", backref="incoming_emails", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<IncomingEmail id={self.id} from={self.sender_email!r} "
            f"processed={self.processed} lead={self.matched_lead_id}>"
        )
