"""ReplyInbox ORM model (Phase 3 Stage 1).

Stores inbound replies / bounces pulled from the sending mailbox so the CRM can
flip a lead into ``replied`` / ``lost`` and stop follow-ups. Linked to the
originating ``outreach_message_id`` when the threading is known.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReplyInbox(Base):
    """An inbound e-mail (reply or bounce) related to an outreach message."""

    __tablename__ = "reply_inbox"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(
        Integer,
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    from_email = Column(String(255), nullable=True, index=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)
    is_bounce = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    received_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReplyInbox id={self.id} from={self.from_email!r} bounce={self.is_bounce}>"
