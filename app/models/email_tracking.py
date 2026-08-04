"""EmailTracking ORM model (Phase 3 Stage 1).

Per-send engagement events derived from the message ``tracking_token``
(open / click webhook hits). Aggregated counters also live on
``outreach_messages`` (open_count / click_count) for fast reporting.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmailTracking(Base):
    """An individual open / click event for a tracked outreach message."""

    __tablename__ = "email_tracking"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(
        Integer,
        ForeignKey("outreach_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(
        String(20), nullable=False, index=True
    )  # open | click
    tracking_token = Column(String(128), nullable=True, index=True)
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(64), nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmailTracking id={self.id} message_id={self.message_id} type={self.event_type!r}>"
