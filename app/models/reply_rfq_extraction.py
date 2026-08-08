"""ReplyRFQExtraction ORM model (Phase 10 Reply Intelligence).

When a reply is classified as an RFQ request (``rfq_request``), the engine
extracts structured quotation requirements — product, quantity, material,
process, deadline and free-form requirements — either deterministically or,
when AI is enabled, with an LLM assist. Each extraction is attached to exactly
one :class:`ReplyAnalysis` and is deleted together with it (``CASCADE``).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.orm import backref, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReplyRFQExtraction(Base):
    """Structured RFQ requirements extracted from a reply."""

    __tablename__ = "reply_rfq_extractions"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(
        Integer,
        ForeignKey("reply_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    product = Column(Text, nullable=True)
    quantity = Column(Text, nullable=True)
    material = Column(Text, nullable=True)
    process = Column(Text, nullable=True)
    deadline = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)

    used_ai = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    analysis = relationship(
        "ReplyAnalysis",
        backref=backref("rfq_extraction", uselist=False, lazy="selectin"),
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ReplyRFQExtraction id={self.id} analysis_id={self.analysis_id} "
            f"used_ai={self.used_ai}>"
        )
