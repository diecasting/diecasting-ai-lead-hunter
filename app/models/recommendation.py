"""Recommendation ORM model (Phase 15.4.1 + 15.4.2 Recommendation Lifecycle).

A :class:`Recommendation` is a *generated* conversion-intelligence suggestion for
a lead, produced whenever :meth:`app.conversion.service.ConversionService.recompute`
refreshes the lead's :class:`ConversionSignal`. It gives the Phase 15.3.3
accept flow a first-class, auditable entity to track:

  generated  -> created by recompute, not yet acted on
  accepted   -> a human accepted it via POST /api/conversion/lead/{id}/accept
  completed  -> the resulting SalesTask was closed (Phase 15.4.2)
  expired    -> superseded by a newer generated recommendation (Phase 15.4.2)

One :class:`Recommendation` is created per ``recompute`` call; the accept
endpoint finds the *latest* ``generated`` one matching the requested action,
flips it to ``accepted``, and (Phase 15.4.2) links the resulting SalesTask via
``sales_task_id``. Phase 15.4.2 also adds ``opportunity_id`` so a downstream
deal can be traced back to the recommendation that spawned it, plus
``completed_at`` / ``expired_at`` timestamps.

Foreign keys are ``SET NULL`` so deleting the underlying lead / signal / task /
opportunity never orphans a recommendation.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Float,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------
REC_STATUS_GENERATED = "generated"
REC_STATUS_ACCEPTED = "accepted"
REC_STATUS_COMPLETED = "completed"
REC_STATUS_EXPIRED = "expired"

REC_STATUSES = (
    REC_STATUS_GENERATED,
    REC_STATUS_ACCEPTED,
    REC_STATUS_COMPLETED,
    REC_STATUS_EXPIRED,
)

# Statuses treated as "active" (still actionable) by downstream queries.
REC_ACTIVE_STATUSES = (REC_STATUS_GENERATED, REC_STATUS_ACCEPTED)


class Recommendation(Base):
    """A generated conversion-intelligence recommendation for a lead."""

    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversion_signal_id = Column(
        Integer,
        ForeignKey("conversion_signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Phase 15.4.2: downstream closure links (all SET NULL).
    sales_task_id = Column(
        Integer,
        ForeignKey("sales_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action = Column(String(40), nullable=False, index=True)
    confidence_score = Column(Float, nullable=True)
    status = Column(
        String(20), nullable=False, default=REC_STATUS_GENERATED,
        server_default="generated", index=True,
    )

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expired_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("CompanyLead", backref="recommendations", lazy="selectin")
    signal = relationship(
        "ConversionSignal", backref="recommendations", lazy="selectin"
    )
    task = relationship("SalesTask", backref="recommendations", lazy="selectin")
    opportunity = relationship(
        "Opportunity", backref="recommendations", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Recommendation id={self.id} company_id={self.company_id} "
            f"action={self.action!r} status={self.status!r}>"
        )
