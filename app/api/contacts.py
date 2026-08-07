"""Phase 8.5 — Contact Intelligence Engine API.

Endpoints (prefix ``/api/contacts``):
* ``POST /api/contacts/discover/{company_id}`` — crawl the company website +
  merge CRM contacts + derive from discovered personal e-mails, then classify
  titles and score purchasing priority, persisting :class:`Contact` rows.
* ``GET  /api/contacts/{company_id}`` — list a company's contacts ranked by
  purchasing priority (with classification + score).
* ``POST /api/contacts/score/{company_id}`` — re-run title classification +
  purchasing scoring on existing contacts (re-prioritisation).

These routes are additive and do not alter the Phase 3 ``/crm-data`` contact
CRUD, nor the Phase 8 ``/api/email`` Email Discovery endpoints.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.contact_intelligence import crud as ccrud
from app.contact_intelligence import service as svc
from app.models.email_address import TYPE_PERSONAL, EmailAddress
from app.models.lead import CompanyLead

router = APIRouter(prefix="/api/contacts", tags=["contact-intelligence"])


# ---------------------------------------------------------------------------
# Response schema (local — does not touch the Phase 3 CRM schemas)
# ---------------------------------------------------------------------------
class ContactRead(BaseModel):
    id: int
    company_id: Optional[int] = None
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    title_category: Optional[str] = None
    seniority: Optional[str] = None
    purchasing_score: Optional[int] = None
    priority: Optional[str] = None
    source: Optional[str] = None
    email_address_id: Optional[int] = None
    is_primary: bool = False
    do_not_contact: bool = False
    rank: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _company_or_404(db: Session, company_id: int) -> CompanyLead:
    company = db.query(CompanyLead).filter(CompanyLead.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _serialize(row, rank: int) -> Dict:
    return {
        "id": row.id,
        "company_id": row.lead_id,
        "full_name": row.full_name,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "phone": row.phone,
        "title": row.title,
        "role": row.role,
        "title_category": row.title_category,
        "seniority": row.seniority,
        "purchasing_score": row.purchasing_score,
        "priority": row.priority,
        "source": row.source,
        "email_address_id": row.email_address_id,
        "is_primary": row.is_primary,
        "do_not_contact": row.do_not_contact,
        "rank": rank,
    }


def _enrich(rows) -> List[Dict]:
    """Attach a 1-based rank and sort by purchasing_score (desc, nulls last)."""
    ranked = sorted(
        rows,
        key=lambda r: (r.purchasing_score if r.purchasing_score is not None else -1),
        reverse=True,
    )
    return [_serialize(r, i + 1) for i, r in enumerate(ranked)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/discover/{company_id}", response_model=dict)
def discover(
    company_id: int,
    db: Session = Depends(get_db),
    max_pages: int = Query(8, ge=1, le=50),
    classify: bool = Query(True),
    score: bool = Query(True),
):
    """Discover + classify + score contacts for a company and persist them."""
    company = _company_or_404(db, company_id)

    has_website = bool(company.website)
    has_crm = bool(company.contact_email or company.contact_emails)
    has_discovered_emails = False
    if not (has_website or has_crm):
        has_discovered_emails = (
            db.query(EmailAddress)
            .filter(
                EmailAddress.company_id == company_id,
                EmailAddress.email_type == TYPE_PERSONAL,
            )
            .first()
            is not None
        )
    if not (has_website or has_crm or has_discovered_emails):
        raise HTTPException(
            status_code=422,
            detail="Company has no website, stored e-mails or discovered "
            "personal e-mails to discover contacts from",
        )

    contacts = svc.discover_for_company(
        db,
        company,
        max_pages=max_pages,
        classify=classify,
        score=score,
    )
    return {
        "company_id": company_id,
        "count": len(contacts),
        "contacts": _enrich(contacts),
    }


@router.get("/{company_id}", response_model=dict)
def list_contacts(company_id: int, db: Session = Depends(get_db)):
    """List a company's contacts, ranked by purchasing priority."""
    _company_or_404(db, company_id)
    rows = ccrud.list_for_company(db, company_id)
    return {
        "company_id": company_id,
        "count": len(rows),
        "contacts": _enrich(rows),
    }


@router.post("/score/{company_id}", response_model=dict)
def rescore(company_id: int, db: Session = Depends(get_db)):
    """Re-run title classification + purchasing scoring on existing contacts."""
    _company_or_404(db, company_id)
    contacts = svc.score_company_contacts(db, company_id)
    return {
        "company_id": company_id,
        "count": len(contacts),
        "contacts": _enrich(contacts),
    }
