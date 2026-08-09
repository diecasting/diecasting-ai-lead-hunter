"""Quotation models (Phase 12.2 Quotation Intelligence Engine).

A :class:`Quote` is the quotation header produced from a structured
:class:`~app.models.product_requirement.ProductRequirement` (Phase 12.1) using
the cost book (:class:`~app.models.cost_rate.CostRate`) and, optionally, a
capability match (:class:`~app.models.manufacturing_capability.ManufacturingCapability`).
It sits on top of the existing pipeline:

    ReplyRFQExtraction -> ProductRequirement -> Opportunity -> Quote -> QuoteLineItem

Quotes reuse the Phase 10/11/12.1 SET NULL FK convention so deleting an
underlying lead / reply / RFQ / opportunity never orphans a quote, and every
line item traces back to a ``cost_rates`` row for audit. :class:`QuoteVersion`
is an append-only snapshot (mirroring ``OpportunityStageHistory``) — there is no
separate history table and no ``QuoteApproval`` yet (deferred).
"""
import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
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


# ---------------------------------------------------------------------------
# Status / line-type vocabulary
# ---------------------------------------------------------------------------
QUOTE_STATUS_DRAFT = "draft"
QUOTE_STATUS_ISSUED = "issued"
QUOTE_STATUS_ACCEPTED = "accepted"
QUOTE_STATUS_REJECTED = "rejected"
QUOTE_STATUS_EXPIRED = "expired"
QUOTE_STATUS_SUPERSEDED = "superseded"

QUOTE_STATUSES = (
    QUOTE_STATUS_DRAFT,
    QUOTE_STATUS_ISSUED,
    QUOTE_STATUS_ACCEPTED,
    QUOTE_STATUS_REJECTED,
    QUOTE_STATUS_EXPIRED,
    QUOTE_STATUS_SUPERSEDED,
)
QUOTE_STATUS_DEFAULT = QUOTE_STATUS_DRAFT

QUOTE_CURRENCY_DEFAULT = "USD"

LINE_MATERIAL = "material"
LINE_DIE_CAST_MACHINE = "die_cast_machine"
LINE_CNC = "cnc"
LINE_TOOLING = "tooling"
LINE_FINISHING = "finishing"
LINE_OVERHEAD = "overhead"
QUOTE_LINE_TYPES = (
    LINE_MATERIAL,
    LINE_DIE_CAST_MACHINE,
    LINE_CNC,
    LINE_TOOLING,
    LINE_FINISHING,
    LINE_OVERHEAD,
)


class Quote(Base):
    """A quotation header derived from a product requirement + cost book."""

    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")

    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requirement_id = Column(
        Integer,
        ForeignKey("product_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rfq_id = Column(
        Integer,
        ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(
        String(20), nullable=False, default=QUOTE_STATUS_DEFAULT,
        server_default=QUOTE_STATUS_DEFAULT,
    )
    currency = Column(
        String(3), nullable=False, default=QUOTE_CURRENCY_DEFAULT,
        server_default=QUOTE_CURRENCY_DEFAULT,
    )

    total_material_cost = Column(Float, nullable=True)
    total_machine_cost = Column(Float, nullable=True)
    total_cnc_cost = Column(Float, nullable=True)
    total_tooling_cost = Column(Float, nullable=True)
    total_finishing_cost = Column(Float, nullable=True)
    total_overhead = Column(Float, nullable=True)
    subtotal = Column(Float, nullable=True)
    margin_pct = Column(Float, nullable=True)
    margin_amount = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)

    valid_until = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    used_ai = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    requirement = relationship(
        "ProductRequirement", backref="quotes", lazy="selectin"
    )
    opportunity = relationship("Opportunity", backref="quotes", lazy="selectin")
    company = relationship("CompanyLead", backref="quotes", lazy="selectin")
    rfq = relationship("ReplyRFQExtraction", backref="quotes", lazy="selectin")
    lines = relationship(
        "QuoteLineItem",
        backref="quote",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="QuoteLineItem.id",
    )
    versions = relationship(
        "QuoteVersion",
        backref="quote",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="QuoteVersion.version",
    )

    def __repr__(self) -> str:
        return (
            f"<Quote id={self.id} status={self.status!r} "
            f"currency={self.currency!r} total_amount={self.total_amount}>"
        )


class QuoteLineItem(Base):
    """A single cost line on a quote, traceable to a cost_rates row."""

    __tablename__ = "quote_line_items"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(
        Integer, ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cost_rate_id = Column(
        Integer, ForeignKey("cost_rates.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    line_type = Column(String(20), nullable=True, index=True)
    description = Column(String(255), nullable=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String(20), nullable=True)
    unit_rate = Column(Float, nullable=True)
    amount = Column(Float, nullable=True)

    used_ai = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<QuoteLineItem id={self.id} quote_id={self.quote_id} "
            f"line_type={self.line_type!r} amount={self.amount}>"
        )


class QuoteVersion(Base):
    """Append-only snapshot of a quote at a point in time (audit)."""

    __tablename__ = "quote_versions"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(
        Integer, ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version = Column(Integer, nullable=True)
    snapshot = Column(Text, nullable=True)
    source = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<QuoteVersion id={self.id} quote_id={self.quote_id} "
            f"version={self.version} source={self.source!r}>"
        )


def _snapshot(quote: "Quote", est: dict) -> str:
    data = {
        "id": quote.id,
        "status": quote.status,
        "currency": quote.currency,
        "totals": {
            "material": quote.total_material_cost,
            "machine": quote.total_machine_cost,
            "cnc": quote.total_cnc_cost,
            "tooling": quote.total_tooling_cost,
            "finishing": quote.total_finishing_cost,
            "overhead": quote.total_overhead,
            "subtotal": quote.subtotal,
            "margin_pct": quote.margin_pct,
            "margin_amount": quote.margin_amount,
            "total_amount": quote.total_amount,
        },
        "lines": est.get("lines", []),
        "used_ai": quote.used_ai,
    }
    return json.dumps(data, default=str)


def create_quote_from_requirement(
    db,
    requirement,
    *,
    opportunity=None,
    rfq=None,
    company_id: Optional[int] = None,
    use_ai: bool = False,
    margin_pct: Optional[float] = None,
    currency: str = QUOTE_CURRENCY_DEFAULT,
    valid_until: Optional[date] = None,
    notes: Optional[str] = None,
) -> "Quote":
    """Build and persist a :class:`Quote` (+ lines + initial version).

    Deterministic cost rollup is produced by
    :func:`app.quotation.estimator.estimate_quote`; when ``use_ai`` is set the
    LLM may refine the margin / price / explanation but never the cost lines.
    The structured requirement may be a persisted ``ProductRequirement`` or an
    in-memory :class:`~app.quotation.estimator.RequirementLike` (no ``id`` ->
    ``requirement_id`` stays NULL).
    """
    from app.models.cost_rate import CostRate
    from app.models.manufacturing_capability import ManufacturingCapability
    from app.quotation.estimator import estimate_quote, DEFAULT_MARGIN_PCT

    rates = db.query(CostRate).all()
    capabilities = (
        db.query(ManufacturingCapability)
        .filter(ManufacturingCapability.active.is_(True))
        .all()
    )
    est = estimate_quote(
        requirement,
        capabilities,
        rates,
        currency=currency,
        margin_pct=margin_pct if margin_pct is not None else DEFAULT_MARGIN_PCT,
        use_ai=use_ai,
    )

    requirement_id = getattr(requirement, "id", None)
    quote = Quote(
        opportunity_id=opportunity.id if opportunity is not None else None,
        requirement_id=requirement_id,
        rfq_id=rfq.id if rfq is not None else None,
        company_id=company_id,
        status=QUOTE_STATUS_DRAFT,
        currency=currency,
        total_material_cost=est["total_material_cost"],
        total_machine_cost=est["total_machine_cost"],
        total_cnc_cost=est["total_cnc_cost"],
        total_tooling_cost=est["total_tooling_cost"],
        total_finishing_cost=est["total_finishing_cost"],
        total_overhead=est["total_overhead"],
        subtotal=est["subtotal"],
        margin_pct=est["margin_pct"],
        margin_amount=est["margin_amount"],
        total_amount=est["suggested_price"],
        valid_until=valid_until,
        notes=notes,
        used_ai=est["used_ai"],
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)

    for ln in est.get("lines", []):
        item = QuoteLineItem(
            quote_id=quote.id,
            cost_rate_id=ln.get("cost_rate_id"),
            line_type=ln.get("line_type"),
            description=ln.get("description"),
            quantity=ln.get("quantity"),
            unit=ln.get("unit"),
            unit_rate=ln.get("unit_rate"),
            amount=ln.get("amount"),
            used_ai=est["used_ai"],
        )
        db.add(item)

    version = QuoteVersion(
        quote_id=quote.id,
        version=quote.version,
        snapshot=_snapshot(quote, est),
        source="ai" if est["used_ai"] else "deterministic",
    )
    db.add(version)
    db.commit()
    db.refresh(quote)
    return quote
