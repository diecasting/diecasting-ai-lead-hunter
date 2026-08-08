"""Cost rate model (Phase 12.1 foundation).

The *price / cost book* for our manufacturing base — the "what does it cost?"
side of the foundation, kept strictly separate from
:class:`~app.models.manufacturing_capability.ManufacturingCapability`
("can we make it?"). A single flexible table covers material cost, machine
hourly cost, labor cost, tooling cost and overhead via the ``category`` column,
so rates are editable and evolvable without code changes.

All rates are normalised by ``code`` (e.g. ``ADC12``, ``dc_800t``, ``cnc_5axis``,
``mold_4cav``, ``factory_overhead``, ``labor_hour``). The estimator (Phase 12)
joins these codes against a structured
:class:`~app.models.product_requirement.ProductRequirement`.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CostRate(Base):
    """A single editable cost / rate line in the manufacturing price book."""

    __tablename__ = "cost_rates"

    id = Column(Integer, primary_key=True, index=True)

    category = Column(String(40), nullable=False, index=True)
    code = Column(String(80), nullable=False, index=True)
    label = Column(String(160), nullable=True)
    unit = Column(String(20), nullable=True)  # kg / hour / piece / lot / pct
    rate = Column(Float, nullable=True)
    currency = Column(String(3), nullable=True)
    effective_from = Column(Date, nullable=True)
    is_default = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    source = Column(String(20), nullable=True, default="manual")  # manual/erp/mes
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "category",
            "code",
            "effective_from",
            name="uq_cost_rates_category_code_effective",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CostRate id={self.id} category={self.category!r} "
            f"code={self.code!r} rate={self.rate} {self.currency}>"
        )
