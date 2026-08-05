"""OutreachEvent ORM model — tracks email send/open/reply/bounce events.

Each row records a single outreach event tied to a lead and (optionally) a
specific ``outreach_messages`` row, enabling reply/open/bounce tracking.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OutreachEvent(Base):
    """A single event in the outreach lifecycle (sent / opened / replied / bounced)."""

    __tablename__ = "outreach_events"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id = Column(
        Integer, ForeignKey("outreach_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type = Column(
        String(20), nullable=False, index=True
    )  # generated | approved | sent | replied | opened | bounced (Phase 4.6)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="outreach_events", lazy="selectin")
    message = relationship("OutreachMessage", backref="events", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OutreachEvent id={self.id} lead_id={self.lead_id} type={self.event_type!r}>"
