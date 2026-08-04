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
            .order_by(CompanyLead.id.desc())
            .all()
        )
        result[stage] = leads
    return result


@router.get("/high-value", response_model=List[CompanyLeadRead])
def high_value(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Return HIGH-priority leads that have not yet been contacted.

    "Not contacted" means lead_status is before ``contacted`` (new / qualified /
    email_generated / approved). These are the hottest actionable prospects.
    """
    leads = (
        db.query(CompanyLead)
        .filter(
            CompanyLead.sales_priority == "HIGH",
            CompanyLead.lead_status.in_(["new", "qualified", "email_generated", "approved"]),
        )
        .order_by(CompanyLead.id.desc())
        .limit(limit)
        .all()
    )
    return leads
