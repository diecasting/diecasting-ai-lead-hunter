"""ReplyAnalysis ORM model — Phase 6 Stage 2.

Stores one AI classification of an inbound customer reply: the detected
intent (interested / rfq_request / technical_question / price_request /
supplier_existing / not_interested / out_of_office / unknown), the
confidence of that classification, and the recommended CRM action. The CRM
automation (status transitions, follow-up cancellation) is applied at
analysis time by ``app.outreach.reply_ai.action``.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReplyAnalysis(Base):
    """A classified customer reply attached to a lead (and optional message)."""

    __tablename__ = "reply_analyses"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reply_text = Column(Text, nullable=False)
    intent = Column(String(40), nullable=False, index=True)
    confidence_score = Column(Float, nullable=True)  # 0-100
    recommended_action = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="reply_analyses", lazy="selectin")
    message = relationship(
        "OutreachMessage", backref="reply_analyses", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReplyAnalysis id={self.id} lead={self.lead_id} intent={self.intent!r} conf={self.confidence_score}>"
