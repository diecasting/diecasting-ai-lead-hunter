"""OutreachMessage ORM model — stores generated sales emails per lead."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OutreachMessage(Base):
    """A generated / drafted / sent sales outreach e-mail for a lead."""

    __tablename__ = "outreach_messages"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    contact_role = Column(String(255), nullable=True)
    status = Column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )  # draft | approved | sent | replied

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="outreach_messages", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OutreachMessage id={self.id} lead_id={self.lead_id} status={self.status!r}>"
