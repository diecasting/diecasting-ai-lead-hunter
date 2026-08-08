"""Manufacturing capability model (Phase 12.1 foundation).

A *capability* record describes what OUR factory can physically make — distinct
from cost (see :class:`~app.models.cost_rate.CostRate`). It is the
"can we make it?" side of the manufacturing intelligence foundation and is used
to match a structured :class:`~app.models.product_requirement.ProductRequirement`
against real press / machine limits.

IMPORTANT: this data is OUR OWN capability. It must never be populated from
prospect-side crawl signals (tonnage / tolerance / cavity extracted from a
customer's website) — those describe the *buyer*, not us.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ManufacturingCapability(Base):
    """A machine / process capability of our own manufacturing base."""

    __tablename__ = "manufacturing_capabilities"

    id = Column(Integer, primary_key=True, index=True)

    # What this capability represents.
    process = Column(String(80), nullable=True, index=True)
    machine_type = Column(String(80), nullable=True)
    tonnage = Column(Integer, nullable=True)  # clamp force in tons (die casting)

    # What it can handle.
    material_compatibility = Column(Text, nullable=True)  # e.g. "ADC12,A380,AZ91D"
    max_part_weight = Column(Float, nullable=True)  # kg, single-cavity max
    tolerance_capability = Column(String(40), nullable=True)  # e.g. "±0.05mm"

    # Lifecycle.
    active = Column(
        Boolean, nullable=False, default=True, server_default="1", index=True
    )

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ManufacturingCapability id={self.id} process={self.process!r} "
            f"tonnage={self.tonnage} active={self.active}>"
        )
