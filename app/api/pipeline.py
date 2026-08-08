"""Sales Pipeline Opportunity API (Phase 11).

Router prefix ``/api/pipeline``. This router *extends* the existing CRM /
reply-intelligence stack with a deal-level pipeline. It never modifies the
existing lead-level ``/crm/pipeline`` endpoint — that endpoint groups
``CompanyLead`` by ``lead_status`` and is left untouched.

Endpoints
---------
  GET  /api/pipeline/opportunities        list opportunities (filterable)
  POST /api/pipeline/opportunities        create an opportunity
  GET  /api/pipeline/opportunities/{id}   get one opportunity (with history)
  PUT  /api/pipeline/opportunities/{id}/stage   advance stage (records history)
  GET  /api/pipeline/summary              weighted pipeline analytics

Opportunities are created either manually via ``POST /opportunities`` or, when
``OPPORTUNITY_AUTOMATION_ENABLED`` is on, automatically from a classified
``rfq_request`` reply by the Phase 11 action-engine hook.
"""
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.opportunity import (
    OPP_CURRENCY_DEFAULT,
    OPP_PRIORITIES,
    OPP_STAGES,
    OPP_STAGE_DEFAULT,
    Opportunity,
    OpportunityStageHistory,
    apply_stage_change,
    default_probability,
    is_open,
)
from app.opportunity_scoring import score_opportunity

router = APIRouter(prefix="/api/pipeline", tags=["sales-pipeline"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class OpportunityRead(BaseModel):
    id: int
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    reply_id: Optional[int] = None
    rfq_id: Optional[int] = None
    stage: str
    amount: Optional[float] = None
    currency: str
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    actual_close_date: Optional[date] = None
    priority: str
    owner: Optional[str] = None
    notes: Optional[str] = None
    used_ai: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    stage_history: List[Dict] = []


class OpportunityCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    reply_id: Optional[int] = None
    rfq_id: Optional[int] = None
    stage: str = OPP_STAGE_DEFAULT
    amount: Optional[float] = None
    currency: str = OPP_CURRENCY_DEFAULT
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[date] = None
    priority: str = "medium"
    owner: Optional[str] = None
    notes: Optional[str] = None
    use_ai: bool = True


class StageChangeRequest(BaseModel):
    stage: str
    note: Optional[str] = None


class PipelineSummary(BaseModel):
    total_open: int
    total_open_value: float
    weighted_value: float
    weighted_value_by_currency: Dict[str, float]
    won_count: int
    won_value: float
    lost_count: int
    lost_value: float
    by_stage: Dict[str, int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _serialize_opportunity(o: Opportunity) -> Dict:
    history = [
        {
            "id": h.id,
            "from_stage": h.from_stage,
            "to_stage": h.to_stage,
            "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            "note": h.note,
        }
        for h in (o.stage_history or [])
    ]
    return {
        "id": o.id,
        "company_id": o.company_id,
        "contact_id": o.contact_id,
        "reply_id": o.reply_id,
        "rfq_id": o.rfq_id,
        "stage": o.stage,
        "amount": o.amount,
        "currency": o.currency,
        "probability": o.probability,
        "expected_close_date": o.expected_close_date,
        "actual_close_date": o.actual_close_date,
        "priority": o.priority,
        "owner": o.owner,
        "notes": o.notes,
        "used_ai": o.used_ai,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
        "stage_history": history,
    }


def _opportunity_or_404(db: Session, opp_id: int) -> Opportunity:
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@router.get("/opportunities", response_model=List[OpportunityRead])
def list_opportunities(
    stage: Optional[str] = None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    priority: Optional[str] = None,
    owner: Optional[str] = None,
    status: Optional[str] = None,  # open | won | lost
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """List opportunities with optional filters.

    ``status`` collapses the stage funnel into three buckets: ``open`` (stage
    not in won/lost), ``won`` and ``lost``.
    """
    q = db.query(Opportunity)
    if stage:
        q = q.filter(Opportunity.stage == stage)
    if company_id is not None:
        q = q.filter(Opportunity.company_id == company_id)
    if contact_id is not None:
        q = q.filter(Opportunity.contact_id == contact_id)
    if priority:
        q = q.filter(Opportunity.priority == priority)
    if owner:
        q = q.filter(Opportunity.owner == owner)
    if status == "open":
        q = q.filter(Opportunity.stage.notin_(["won", "lost"]))
    elif status == "won":
        q = q.filter(Opportunity.stage == "won")
    elif status == "lost":
        q = q.filter(Opportunity.stage == "lost")
    rows = q.order_by(Opportunity.id.desc()).limit(limit).all()
    return [_serialize_opportunity(o) for o in rows]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@router.post("/opportunities", response_model=OpportunityRead, status_code=201)
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db)):
    if payload.stage not in OPP_STAGES:
        raise HTTPException(
            status_code=422, detail=f"stage must be one of: {', '.join(OPP_STAGES)}"
        )
    if payload.priority not in OPP_PRIORITIES:
        raise HTTPException(
            status_code=422, detail=f"priority must be one of: {', '.join(OPP_PRIORITIES)}"
        )

    probability = payload.probability
    used_ai = False
    if probability is None:
        # Deterministic baseline (optionally AI-enhanced) when not supplied.
        score, used_ai = score_opportunity(
            payload.stage,
            company_priority=payload.priority,
            use_ai=payload.use_ai,
        )
        probability = score.get("probability")

    opp = Opportunity(
        company_id=payload.company_id,
        contact_id=payload.contact_id,
        reply_id=payload.reply_id,
        rfq_id=payload.rfq_id,
        stage=payload.stage,
        amount=payload.amount,
        currency=payload.currency,
        probability=probability,
        priority=payload.priority,
        owner=payload.owner,
        notes=payload.notes,
        expected_close_date=payload.expected_close_date,
        used_ai=bool(used_ai),
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    history = OpportunityStageHistory(
        opportunity_id=opp.id,
        from_stage=None,
        to_stage=payload.stage,
        note="Created",
    )
    db.add(history)
    db.commit()
    db.refresh(opp)
    return _serialize_opportunity(opp)


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------
@router.get("/opportunities/{opp_id}", response_model=OpportunityRead)
def get_opportunity(opp_id: int, db: Session = Depends(get_db)):
    return _serialize_opportunity(_opportunity_or_404(db, opp_id))


# ---------------------------------------------------------------------------
# Stage transition
# ---------------------------------------------------------------------------
@router.put("/opportunities/{opp_id}/stage", response_model=OpportunityRead)
def change_stage(
    opp_id: int, payload: StageChangeRequest, db: Session = Depends(get_db)
):
    if payload.stage not in OPP_STAGES:
        raise HTTPException(
            status_code=422, detail=f"stage must be one of: {', '.join(OPP_STAGES)}"
        )
    opp = _opportunity_or_404(db, opp_id)
    updated = apply_stage_change(db, opp, payload.stage, note=payload.note)
    return _serialize_opportunity(updated)


# ---------------------------------------------------------------------------
# Pipeline summary / weighted analytics
# ---------------------------------------------------------------------------
@router.get("/summary", response_model=PipelineSummary)
def pipeline_summary(db: Session = Depends(get_db)):
    """Weighted pipeline analytics computed at read-time (no cached counters).

    * ``weighted_value`` = Σ(amount × probability/100) over *open* opportunities,
      aggregated across currencies in ``weighted_value_by_currency``.
    * ``won_value`` / ``lost_value`` sum the full amount of terminal deals.
    """
    rows = db.query(Opportunity).all()

    total_open = 0
    total_open_value = 0.0
    weighted_value = 0.0
    weighted_by_currency: Dict[str, float] = {}
    won_count = 0
    won_value = 0.0
    lost_count = 0
    lost_value = 0.0
    by_stage: Dict[str, int] = {s: 0 for s in OPP_STAGES}

    for o in rows:
        by_stage[o.stage] = by_stage.get(o.stage, 0) + 1
        if o.stage == "won":
            won_count += 1
            won_value += o.amount or 0.0
            continue
        if o.stage == "lost":
            lost_count += 1
            lost_value += o.amount or 0.0
            continue
        if not is_open(o.stage):
            continue
        total_open += 1
        total_open_value += o.amount or 0.0
        weight = (o.probability if o.probability is not None else default_probability(o.stage))
        weighted = (o.amount or 0.0) * (weight / 100.0)
        weighted_value += weighted
        cur = o.currency or OPP_CURRENCY_DEFAULT
        weighted_by_currency[cur] = weighted_by_currency.get(cur, 0.0) + weighted

    return PipelineSummary(
        total_open=total_open,
        total_open_value=round(total_open_value, 2),
        weighted_value=round(weighted_value, 2),
        weighted_value_by_currency={k: round(v, 2) for k, v in weighted_by_currency.items()},
        won_count=won_count,
        won_value=round(won_value, 2),
        lost_count=lost_count,
        lost_value=round(lost_value, 2),
        by_stage=by_stage,
    )
