"""FollowUpSequence / OutreachFollowUp ORM models — Phase 6 Stage 1.

A :class:`FollowUpSequence` defines the cadence for follow-up outreach as a
JSON list of steps, e.g. ``[{"delay_days": 3, "template": "technical_followup"},
{"delay_days": 7, "template": "rfq_followup"}]``.

An :class:`OutreachFollowUp` is one scheduled follow-up for a lead, tied to
the original sent message and the sequence step. Its ``status`` lifecycle:
pending → generated → sent (or cancelled when the lead replies / converts /
closes).
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FollowUpSequence(Base):
    """A named, ordered set of follow-up steps."""

    __tablename__ = "followup_sequences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    steps = Column(Text, nullable=False)  # JSON list of {delay_days, template}
    enabled = Column(
        Boolean,
        nullable=False, default=True, server_default="1", index=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    followups = relationship(
        "OutreachFollowUp", backref="sequence", lazy="selectin"
    )

    def steps_list(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.steps or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FollowUpSequence id={self.id} name={self.name!r} enabled={self.enabled}>"


class OutreachFollowUp(Base):
    """One scheduled follow-up email for a lead."""

    __tablename__ = "outreach_followups"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    original_message_id = Column(
        Integer, ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    sequence_id = Column(
        Integer, ForeignKey("followup_sequences.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    step_number = Column(Integer, nullable=False, default=1)
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        String(20), nullable=False, default="pending",
        server_default="pending", index=True,
    )  # pending | generated | sent | cancelled
    message_id = Column(
        Integer, ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="outreach_followups", lazy="selectin")
    original_message = relationship(
        "OutreachMessage", foreign_keys=[original_message_id], lazy="selectin"
    )
    message = relationship(
        "OutreachMessage", foreign_keys=[message_id], lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OutreachFollowUp id={self.id} lead={self.lead_id} step={self.step_number} status={self.status!r}>"
