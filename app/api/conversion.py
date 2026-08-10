"""Conversion Intelligence Read API (Phase 15.3.1 / 15.3.2).

Read-only endpoints exposing the deterministic conversion-intelligence
snapshot computed by :mod:`app.conversion` (Phase 15.1 / 15.2.1). This router
is strictly a *view* layer:

  GET /api/conversion/lead/{lead_id}   current conversion intelligence for one lead
  GET /api/conversion/hot-leads         leads ranked by temperature / priority (15.3.2)

No SalesTask creation, no accept endpoint, no mutations, no migrations.

The snapshot is produced by :class:`app.conversion.service.ConversionService`
and stored on the one-row-per-lead :class:`app.models.conversion_signal.ConversionSignal`.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.conversion import execution as conv_execution
from app.conversion.service import ConversionService
from app.database import get_db
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.recommendation import (
    REC_STATUS_ACCEPTED,
    REC_STATUS_GENERATED,
    Recommendation,
)
from app.models.sales_task import SalesTask

router = APIRouter(prefix="/api/conversion", tags=["conversion-intelligence"])

# Priority ordering for ranking (higher value = higher rank).
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------
class ConversionSignalRead(BaseModel):
    lead_id: int
    intent_score: Optional[int] = None
    dominant_intent: Optional[str] = None
    signal_sources: Optional[dict] = None
    temperature_score: Optional[int] = None
    temperature_label: Optional[str] = None
    next_action: Optional[str] = None
    next_action_priority: Optional[str] = None
    next_action_reason: Optional[str] = None
    computed_at: Optional[str] = None


class HotLeadRead(BaseModel):
    lead_id: int
    company_name: Optional[str] = None
    intent_score: Optional[int] = None
    dominant_intent: Optional[str] = None
    temperature_score: Optional[int] = None
    temperature_label: Optional[str] = None
    next_action: Optional[str] = None
    next_action_priority: Optional[str] = None
    next_action_reason: Optional[str] = None
    computed_at: Optional[str] = None


class AcceptRequest(BaseModel):
    action: str
    force: bool = False


class AcceptResult(BaseModel):
    task_id: int
    lead_id: int
    title: str
    priority: str
    status: str
    category: Optional[str] = None
    accepted_action: str
    already_exists: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _serialize_signal(signal: ConversionSignal, company_name: Optional[str] = None):
    sources = None
    if signal.signal_sources:
        try:
            sources = json.loads(signal.signal_sources)
        except (json.JSONDecodeError, TypeError):
            sources = None
    computed = signal.computed_at.isoformat() if signal.computed_at else None
    return ConversionSignalRead(
        lead_id=signal.lead_id,
        intent_score=signal.intent_score,
        dominant_intent=signal.dominant_intent,
        signal_sources=sources,
        temperature_score=signal.temperature_score,
        temperature_label=signal.temperature_label,
        next_action=signal.next_action,
        next_action_priority=signal.next_action_priority,
        next_action_reason=signal.next_action_reason,
        computed_at=computed,
    )


def _serialize_hot_lead(signal: ConversionSignal, company_name: Optional[str] = None):
    computed = signal.computed_at.isoformat() if signal.computed_at else None
    return HotLeadRead(
        lead_id=signal.lead_id,
        company_name=company_name,
        intent_score=signal.intent_score,
        dominant_intent=signal.dominant_intent,
        temperature_score=signal.temperature_score,
        temperature_label=signal.temperature_label,
        next_action=signal.next_action,
        next_action_priority=signal.next_action_priority,
        next_action_reason=signal.next_action_reason,
        computed_at=computed,
    )


def _accept_recommendation(db: Session, *, lead_id: int, action: str) -> None:
    """Mark the latest ``generated`` Recommendation for (lead, action) accepted.

    Best-effort: if no generated recommendation exists (e.g. recompute never ran
    for this lead), nothing is marked and the accept flow continues unchanged.
    """
    rec = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == lead_id,
            Recommendation.action == action,
            Recommendation.status == REC_STATUS_GENERATED,
        )
        .order_by(Recommendation.id.desc())
        .first()
    )
    if rec is None:
        return
    rec.status = REC_STATUS_ACCEPTED
    rec.accepted_at = datetime.now(timezone.utc)
    db.add(rec)
    db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/lead/{lead_id}", response_model=ConversionSignalRead)
def get_conversion_signal(lead_id: int, db: Session = Depends(get_db)):
    """Return the current conversion intelligence snapshot for one lead.

    Returns 404 if the lead does not exist or if no :class:`ConversionSignal`
    has been computed for it yet.
    """
    lead = (
        db.query(CompanyLead)
        .filter(CompanyLead.id == lead_id)
        .first()
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    signal = ConversionService(db).get_signal(lead_id)
    if signal is None:
        raise HTTPException(
            status_code=404, detail="Conversion signal not found for this lead"
        )

    return _serialize_signal(signal)


# ---------------------------------------------------------------------------
# Hot leads (ranked conversion opportunities)
# ---------------------------------------------------------------------------
@router.get("/hot-leads", response_model=List[HotLeadRead])
def list_hot_leads(
    label: Optional[str] = Query(None, pattern="^(hot|warm|cold)$"),
    action: Optional[str] = Query(
        None,
        pattern="^(prepare_quote|send_capability_case|stop_sequence|suppress_contact)$",
    ),
    min_temperature: Optional[int] = Query(None, ge=0, le=100),
    include_suppressed: bool = False,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return leads ranked by conversion intelligence / temperature / priority.

    Ranking: ``next_action_priority`` (high > medium > low) then
    ``temperature_score`` descending. Leads with ``do_not_contact = true`` are
    excluded by default; pass ``include_suppressed=true`` to include them.

    Optional filters: ``label`` (hot|warm|cold), ``action`` (one of the four
    recommendation actions), ``min_temperature`` (0..100), ``limit`` (default 50).
    """
    q = db.query(ConversionSignal).join(
        CompanyLead, CompanyLead.id == ConversionSignal.lead_id
    )

    if not include_suppressed:
        q = q.filter(CompanyLead.do_not_contact.is_(False))

    if label is not None:
        q = q.filter(ConversionSignal.temperature_label == label)
    if action is not None:
        q = q.filter(ConversionSignal.next_action == action)
    if min_temperature is not None:
        q = q.filter(ConversionSignal.temperature_score >= min_temperature)

    # Fetch candidates, then rank in Python so priority ordering is explicit and
    # DB-agnostic (SQLite vs Postgres sort of NULL/enum differs).
    signals = q.all()
    leads_by_id = {lead.id: lead for lead in db.query(CompanyLead).all()}

    ranked = sorted(
        signals,
        key=lambda s: (
            _PRIORITY_RANK.get(s.next_action_priority, 3),
            -(s.temperature_score if s.temperature_score is not None else -1),
        ),
    )

    out: List[HotLeadRead] = []
    for sig in ranked[:limit]:
        company = leads_by_id.get(sig.lead_id)
        company_name = company.name if company is not None else None
        out.append(_serialize_hot_lead(sig, company_name))
    return out


# ---------------------------------------------------------------------------
# Accept a recommendation -> SalesTask (human-in-the-loop, 15.3.3)
# ---------------------------------------------------------------------------
@router.post("/lead/{lead_id}/accept", response_model=AcceptResult)
def accept_recommendation(
    lead_id: int, payload: AcceptRequest, db: Session = Depends(get_db)
):
    """Accept a conversion recommendation and create a SalesTask.

    The requested ``action`` must match ``signal.next_action`` unless
    ``force=true``. An open task for the same recommendation is returned instead
    of duplicated (``already_exists=true``). Safety actions
    (``stop_sequence`` / ``suppress_contact``) set ``lead.do_not_contact=True``
    after acceptance. Returns 404 if the lead / signal is missing, 409 if the
    action mismatches the recommendation and ``force`` is not set.
    """
    lead = (
        db.query(CompanyLead)
        .filter(CompanyLead.id == lead_id)
        .first()
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    signal = ConversionService(db).get_signal(lead_id)
    if signal is None:
        raise HTTPException(
            status_code=404, detail="Conversion signal not found for this lead"
        )

    # Phase 15.4.1: mark the latest generated Recommendation for this action
    # as accepted. This is the auditable lifecycle event; the SalesTask path
    # below is unchanged.
    _accept_recommendation(db, lead_id=lead.id, action=payload.action)

    try:
        task, already_exists = conv_execution.create_task_from_recommendation(
            db, lead, signal, payload.action, force=payload.force
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return AcceptResult(
        task_id=task.id,
        lead_id=lead.id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        category=task.category,
        accepted_action=payload.action,
        already_exists=already_exists,
    )
