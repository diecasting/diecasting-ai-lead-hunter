"""ConversionSignal ORM model (Phase 15.1.1 Conversion Signal Foundation).

A :class:`ConversionSignal` is the *latest* computed conversion-intelligence
snapshot for a lead. It currently holds the deterministic **intent score**
(Phase 15.1.2) and the dominant driving intent; later phases (15.1.3
temperature, 15.1.4 next-action) will extend the same table.

One row per lead (upserted by :class:`app.conversion.service.ConversionService`).
``lead_id`` is ``SET NULL`` so deleting the underlying ``CompanyLead`` never
orphans the signal — the descriptive fields (score, dominant intent, sources)
remain for analytics.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversionSignal(Base):
    """Latest deterministic conversion-intelligence snapshot for a lead."""

    __tablename__ = "conversion_signals"

    id = Column(Integer, primary_key=True, index=True)

    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Phase 15.1.2: deterministic intent score (signed, -100..100).
    # Positive = strong buying intent; negative = disinterest / spam signal.
    intent_score = Column(Integer, nullable=True, index=True)

    # The intent class that contributed the most (by absolute weighted value)
    # to the score; None when no classified reply drove the score.
    dominant_intent = Column(String(40), nullable=True)

    # JSON-encoded provenance: per-reply + per-event weighted contributions,
    # method version, half-life, computed_at. Kept as Text (JSON string) to
    # stay portable across SQLite (tests) and PostgreSQL (prod).
    signal_sources = Column(Text, nullable=True)

    computed_at = Column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    lead = relationship(
        "CompanyLead", backref="conversion_signals", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ConversionSignal id={self.id} lead_id={self.lead_id} "
            f"intent_score={self.intent_score} dominant={self.dominant_intent!r}>"
        )
