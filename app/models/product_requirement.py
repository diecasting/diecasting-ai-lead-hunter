"""Product requirement model (Phase 12.1 foundation).

The *structured* interpretation of a customer RFQ. Phase 10 captures the raw
reply text in :class:`~app.models.reply_rfq_extraction.ReplyRFQExtraction`
(free-form ``product / quantity / material / process / deadline / requirements``);
this model is the normalised, quotation-ready view (weight, material, process,
annual volume, tolerance, finishing, complexity) that the cost estimator
(Phase 12) consumes.

It links back to the originating RFQ and the deal it belongs to, but every FK is
SET NULL so deleting an underlying record never orphans the requirement.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductRequirement(Base):
    """A structured, quotation-ready interpretation of a customer RFQ."""

    __tablename__ = "product_requirements"

    id = Column(Integer, primary_key=True, index=True)

    # Provenance (all SET NULL so history survives downstream deletions).
    rfq_id = Column(
        Integer,
        ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Structured requirement (the quotation-ready view of an RFQ).
    weight = Column(Float, nullable=True)  # kg per part (single cavity)
    material = Column(String(80), nullable=True)  # normalised alloy code
    process = Column(String(80), nullable=True)  # normalised process
    annual_volume = Column(Integer, nullable=True)  # pieces / year
    tolerance = Column(String(40), nullable=True)  # e.g. "±0.05mm"
    finishing = Column(String(80), nullable=True)  # e.g. anodizing / painting
    complexity = Column(String(20), nullable=True)  # low / medium / high

    used_ai = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    rfq = relationship(
        "ReplyRFQExtraction", backref="product_requirements", lazy="selectin"
    )
    opportunity = relationship(
        "Opportunity", backref="product_requirements", lazy="selectin"
    )
    company = relationship(
        "CompanyLead", backref="product_requirements", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ProductRequirement id={self.id} material={self.material!r} "
            f"weight={self.weight} process={self.process!r}>"
        )
