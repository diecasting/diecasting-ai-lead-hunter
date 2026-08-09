"""Quotation Intelligence Engine API (Phase 12.2).

Router prefix ``/api/quotation``. Exposes a deterministic cost-preview endpoint
(``/estimate``, no persistence) and CRUD-ish endpoints for persisted quotes.

Estimation reuses :func:`app.quotation.estimator.estimate_quote` and the Phase
12.1 cost book / capability tables; the LLM may only refine margin / price /
explanation (never the cost math).
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.quotation import (
    QUOTE_CURRENCY_DEFAULT,
    Quote,
    QuoteLineItem,
    QuoteVersion,
    create_quote_from_requirement,
)
from app.models.cost_rate import CostRate
from app.models.manufacturing_capability import ManufacturingCapability
from app.models.opportunity import Opportunity
from app.models.reply_rfq_extraction import ReplyRFQExtraction
from app.models.product_requirement import ProductRequirement
from app.quotation.estimator import (
    DEFAULT_MARGIN_PCT,
    RequirementLike,
    estimate_quote,
)

router = APIRouter(prefix="/api/quotation", tags=["quotation"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class QuoteLineItemRead(BaseModel):
    id: int
    quote_id: int
    cost_rate_id: Optional[int] = None
    line_type: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_rate: Optional[float] = None
    amount: Optional[float] = None
    used_ai: bool = False


class QuoteVersionRead(BaseModel):
    id: int
    quote_id: int
    version: Optional[int] = None
    snapshot: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None


class QuoteRead(BaseModel):
    id: int
    version: int
    opportunity_id: Optional[int] = None
    requirement_id: Optional[int] = None
    rfq_id: Optional[int] = None
    company_id: Optional[int] = None
    status: str
    currency: str
    total_material_cost: Optional[float] = None
    total_machine_cost: Optional[float] = None
    total_cnc_cost: Optional[float] = None
    total_tooling_cost: Optional[float] = None
    total_finishing_cost: Optional[float] = None
    total_overhead: Optional[float] = None
    subtotal: Optional[float] = None
    margin_pct: Optional[float] = None
    margin_amount: Optional[float] = None
    total_amount: Optional[float] = None
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    used_ai: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    lines: List[QuoteLineItemRead] = []
    versions: List[QuoteVersionRead] = []


class EstimateRequest(BaseModel):
    requirement_id: Optional[int] = None
    weight: Optional[float] = None
    material: Optional[str] = None
    process: Optional[str] = None
    annual_volume: Optional[int] = None
    tolerance: Optional[str] = None
    finishing: Optional[str] = None
    complexity: Optional[str] = None
    currency: str = QUOTE_CURRENCY_DEFAULT
    margin_pct: Optional[float] = None
    use_ai: bool = False


class QuoteCreate(BaseModel):
    requirement_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    rfq_id: Optional[int] = None
    company_id: Optional[int] = None
    weight: Optional[float] = None
    material: Optional[str] = None
    process: Optional[str] = None
    annual_volume: Optional[int] = None
    tolerance: Optional[str] = None
    finishing: Optional[str] = None
    complexity: Optional[str] = None
    currency: str = QUOTE_CURRENCY_DEFAULT
    margin_pct: Optional[float] = None
    use_ai: bool = False
    valid_until: Optional[date] = None
    notes: Optional[str] = None


class EstimateResponse(BaseModel):
    lines: List[QuoteLineItemRead] = []
    total_material_cost: float = 0.0
    total_machine_cost: float = 0.0
    total_cnc_cost: float = 0.0
    total_tooling_cost: float = 0.0
    total_finishing_cost: float = 0.0
    total_overhead: float = 0.0
    subtotal: float = 0.0
    total_cost: float = 0.0
    suggested_price: float = 0.0
    margin_pct: Optional[float] = None
    margin_amount: Optional[float] = None
    currency: str = QUOTE_CURRENCY_DEFAULT
    used_ai: bool = False
    explanation: str = ""
    feasible: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_requirement(db: Session, payload):
    req_id = payload.requirement_id
    if req_id is not None:
        pr = db.query(ProductRequirement).filter(ProductRequirement.id == req_id).first()
        if pr is None:
            raise HTTPException(status_code=404, detail="Requirement not found")
        return pr
    return RequirementLike(
        weight=payload.weight,
        material=payload.material,
        process=payload.process,
        annual_volume=payload.annual_volume,
        tolerance=payload.tolerance,
        finishing=payload.finishing,
        complexity=payload.complexity,
    )


def _serialize_line(l: QuoteLineItem) -> dict:
    return {
        "id": l.id,
        "quote_id": l.quote_id,
        "cost_rate_id": l.cost_rate_id,
        "line_type": l.line_type,
        "description": l.description,
        "quantity": l.quantity,
        "unit": l.unit,
        "unit_rate": l.unit_rate,
        "amount": l.amount,
        "used_ai": l.used_ai,
    }


def _serialize_version(v: QuoteVersion) -> dict:
    return {
        "id": v.id,
        "quote_id": v.quote_id,
        "version": v.version,
        "snapshot": v.snapshot,
        "source": v.source,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _serialize_quote(q: Quote) -> dict:
    return {
        "id": q.id,
        "version": q.version,
        "opportunity_id": q.opportunity_id,
        "requirement_id": q.requirement_id,
        "rfq_id": q.rfq_id,
        "company_id": q.company_id,
        "status": q.status,
        "currency": q.currency,
        "total_material_cost": q.total_material_cost,
        "total_machine_cost": q.total_machine_cost,
        "total_cnc_cost": q.total_cnc_cost,
        "total_tooling_cost": q.total_tooling_cost,
        "total_finishing_cost": q.total_finishing_cost,
        "total_overhead": q.total_overhead,
        "subtotal": q.subtotal,
        "margin_pct": q.margin_pct,
        "margin_amount": q.margin_amount,
        "total_amount": q.total_amount,
        "valid_until": q.valid_until,
        "notes": q.notes,
        "used_ai": q.used_ai,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        "lines": [_serialize_line(l) for l in (q.lines or [])],
        "versions": [_serialize_version(v) for v in (q.versions or [])],
    }


def _estimate_response(est: dict) -> EstimateResponse:
    return EstimateResponse(
        lines=[
            QuoteLineItemRead(
                id=0,
                quote_id=0,
                cost_rate_id=ln.get("cost_rate_id"),
                line_type=ln.get("line_type"),
                description=ln.get("description"),
                quantity=ln.get("quantity"),
                unit=ln.get("unit"),
                unit_rate=ln.get("unit_rate"),
                amount=ln.get("amount"),
                used_ai=ln.get("used_ai", False),
            )
            for ln in est.get("lines", [])
        ],
        total_material_cost=est.get("total_material_cost") or 0.0,
        total_machine_cost=est.get("total_machine_cost") or 0.0,
        total_cnc_cost=est.get("total_cnc_cost") or 0.0,
        total_tooling_cost=est.get("total_tooling_cost") or 0.0,
        total_finishing_cost=est.get("total_finishing_cost") or 0.0,
        total_overhead=est.get("total_overhead") or 0.0,
        subtotal=est.get("subtotal") or 0.0,
        total_cost=est.get("total_cost") or 0.0,
        suggested_price=est.get("suggested_price") or 0.0,
        margin_pct=est.get("margin_pct"),
        margin_amount=est.get("margin_amount") or 0.0,
        currency=est.get("currency", QUOTE_CURRENCY_DEFAULT),
        used_ai=est.get("used_ai", False),
        explanation=est.get("explanation") or "",
        feasible=est.get("feasible"),
    )


def _load_rates(db: Session):
    rates = db.query(CostRate).all()
    capabilities = (
        db.query(ManufacturingCapability)
        .filter(ManufacturingCapability.active.is_(True))
        .all()
    )
    return rates, capabilities


# ---------------------------------------------------------------------------
# Estimate (no persistence)
# ---------------------------------------------------------------------------
@router.post("/estimate", response_model=EstimateResponse)
def estimate(payload: EstimateRequest, db: Session = Depends(get_db)):
    requirement = _build_requirement(db, payload)
    rates, capabilities = _load_rates(db)
    est = estimate_quote(
        requirement,
        capabilities,
        rates,
        currency=payload.currency,
        margin_pct=payload.margin_pct if payload.margin_pct is not None else DEFAULT_MARGIN_PCT,
        use_ai=payload.use_ai,
    )
    return _estimate_response(est)


# ---------------------------------------------------------------------------
# Create (persist)
# ---------------------------------------------------------------------------
@router.post("", response_model=QuoteRead, status_code=201)
def create_quote(payload: QuoteCreate, db: Session = Depends(get_db)):
    requirement = _build_requirement(db, payload)
    opportunity = (
        db.query(Opportunity).filter(Opportunity.id == payload.opportunity_id).first()
        if payload.opportunity_id is not None else None
    )
    rfq = (
        db.query(ReplyRFQExtraction).filter(ReplyRFQExtraction.id == payload.rfq_id).first()
        if payload.rfq_id is not None else None
    )
    quote = create_quote_from_requirement(
        db,
        requirement,
        opportunity=opportunity,
        rfq=rfq,
        company_id=payload.company_id,
        use_ai=payload.use_ai,
        margin_pct=payload.margin_pct,
        currency=payload.currency,
        valid_until=payload.valid_until,
        notes=payload.notes,
    )
    return _serialize_quote(quote)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@router.get("", response_model=List[QuoteRead])
def list_quotes(
    company_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(Quote)
    if company_id is not None:
        q = q.filter(Quote.company_id == company_id)
    if opportunity_id is not None:
        q = q.filter(Quote.opportunity_id == opportunity_id)
    if status:
        q = q.filter(Quote.status == status)
    rows = q.order_by(Quote.id.desc()).limit(limit).all()
    return [_serialize_quote(o) for o in rows]


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------
@router.get("/{quote_id}", response_model=QuoteRead)
def get_quote(quote_id: int, db: Session = Depends(get_db)):
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if q is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return _serialize_quote(q)
