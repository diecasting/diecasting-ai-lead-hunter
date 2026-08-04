"""CRM API routes (Phase 2.5).

- GET  /crm/pipeline    — leads grouped by sales pipeline status.
- GET  /crm/high-value  — HIGH-priority leads that have not yet been contacted.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.database import get_db
from app.models.lead import CompanyLead
from app.schemas.lead import CompanyLeadRead

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/pipeline", response_model=Dict[str, List[CompanyLeadRead]])
def pipeline(
    db: Session = Depends(get_db),
    statuses: str = Query(
        None,
        description="Comma-separated lead_status values to include; empty = all",
    ),
):
    """Return leads grouped by their ``lead_status`` pipeline stage.

    Example response:
        {"new": [...], "qualified": [...], "contacted": [...]}
    """
    from app.outreach.workflow import ALL_STATUSES

    requested = [s.strip() for s in (statuses or "").split(",") if s.strip()]
    stages = requested or ALL_STATUSES

    result: Dict[str, List[CompanyLead]] = {}
    for stage in stages:
        leads = (
            db.query(CompanyLead)
            .filter(CompanyLead.lead_status == stage)
            .order_by(CompanyLead.lead_score.desc().nullslast())
            .all()
        )
        result[stage] = leads
    return result


@router.get("/high-value", response_model=List[CompanyLeadRead])
def high_value(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Return the highest-value leads that have not yet been contacted.

    "Not contacted" means lead_status is before ``contacted`` (new / qualified /
    email_generated / approved) and ``sales_priority`` is HIGH. Within that set,
    leads are auto-sorted by ``lead_score`` (descending) so the hottest,
    highest-fit prospects come first.
    """
    leads = (
        db.query(CompanyLead)
        .filter(
            CompanyLead.sales_priority == "HIGH",
            CompanyLead.lead_status.in_(["new", "qualified", "email_generated", "approved"]),
        )
        .order_by(
            CompanyLead.lead_score.desc().nullslast(),
            CompanyLead.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return leads


@router.get("/ranking")
def ranking(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=500),
    min_score: int = Query(0, ge=0, le=100, description="Only leads with lead_score >= this"),
    priority: str = Query(
        None, description="Filter by priority: HIGH / MEDIUM / LOW"
    ),
):
    """Return the top leads ranked by the composite ``lead_score``.

    Supports optional filters:
      * ``min_score`` — only include leads scoring at least this (0–100).
      * ``priority`` — only include leads with the given priority label.

    The response groups leads by ``priority`` and also returns the flat
    ``ranked`` list (sorted by score desc) with their score + breakdown so the
    front-end / export can highlight *why* each lead ranks where it does.
    """
    valid_priority = {p for p in ("HIGH", "MEDIUM", "LOW")}
    pfilter = (priority or "").upper().strip()
    if pfilter and pfilter not in valid_priority:
        pfilter = ""

    query = db.query(CompanyLead)
    if pfilter:
        query = query.filter(CompanyLead.priority == pfilter)
    if min_score > 0:
        query = query.filter(CompanyLead.lead_score >= min_score)

    leads = (
        query.order_by(
            CompanyLead.lead_score.desc().nullslast(), CompanyLead.id.desc()
        )
        .limit(limit)
        .all()
    )

    grouped: Dict[str, List[CompanyLead]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    ranked = []
    for lead in leads:
        grp = lead.priority or "LOW"
        if grp not in grouped:
            grouped[grp] = []
        grouped[grp].append(lead)
        ranked.append(lead)

    return {
        "count": len(ranked),
        "filters": {"min_score": min_score, "priority": pfilter or None},
        "by_priority": grouped,
        "ranked": ranked,
    }
