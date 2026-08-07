"""Phase 8 — Email Discovery & Verification Engine API.

Endpoints (prefix ``/api/email``):
* ``POST /api/email/discover/{company_id}`` — crawl the company website + pull
  CRM e-mails, persist :class:`EmailAddress` rows (optionally verify them).
* ``POST /api/email/verify`` — verify a list of e-mails (or every stored e-mail
  for a company) and persist the deliverability verdicts.
* ``GET  /api/email/{company_id}`` — list discovered e-mails for a company,
  ranked by discovery priority.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.email_discovery import crud as ecrud
from app.email_discovery import service as svc
from app.email_discovery.patterns import infer_patterns
from app.email_discovery.ranking import rank_score
from app.models.lead import CompanyLead

router = APIRouter(prefix="/api/email", tags=["email-discovery"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class VerifyRequest(BaseModel):
    company_id: Optional[int] = Field(
        None, description="Verify every stored e-mail for this company."
    )
    emails: Optional[List[str]] = Field(
        None, description="Explicit list of addresses to verify (standalone or with company_id)."
    )


class EmailRead(BaseModel):
    id: int
    company_id: Optional[int] = None
    email: str
    source: str
    email_type: str
    verification_status: str
    verification_score: Optional[int] = None
    verified_at: Optional[str] = None
    created_at: Optional[str] = None
    rank_score: int = 0


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
        "company_id": row.company_id,
        "email": row.email,
        "source": row.source,
        "email_type": row.email_type,
        "verification_status": row.verification_status,
        "verification_score": row.verification_score,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "rank_score": rank,
    }


def _enrich(rows) -> List[Dict]:
    """Attach a computed rank_score and sort by it (desc) then e-mail."""
    out = []
    for r in rows:
        rs = rank_score(
            r.email,
            email_type=r.email_type,
            verification_status=r.verification_status,
            verification_score=r.verification_score,
            source=r.source,
        )
        out.append(_serialize(r, rs))
    out.sort(key=lambda x: (-x["rank_score"], x["email"]))
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/discover/{company_id}", response_model=dict)
def discover(
    company_id: int,
    db: Session = Depends(get_db),
    verify: bool = Query(False, description="Also run the verification pipeline."),
    max_pages: int = Query(8, ge=1, le=50),
):
    """Crawl the company site + merge CRM e-mails, persisting EmailAddress rows."""
    company = _company_or_404(db, company_id)
    has_website = bool(company.website)
    has_crm = bool(company.contact_email or company.contact_emails)
    if not has_website and not has_crm:
        raise HTTPException(
            status_code=422,
            detail="Company has no website or stored e-mails to discover from",
        )

    rows = svc.discover_for_company(
        db,
        company,
        max_pages=max_pages,
        verify=verify,
        smtp_enabled=settings.email_verify_smtp_enabled,
        catch_all_enabled=settings.email_verify_catch_all_enabled,
    )

    domain = svc.company_domain(company)
    patterns = infer_patterns([r.email for r in rows], domain) if domain else []
    return {
        "company_id": company_id,
        "count": len(rows),
        "patterns": patterns,
        "emails": _enrich(rows),
    }


@router.post("/verify", response_model=dict)
def verify(request: VerifyRequest, db: Session = Depends(get_db)):
    """Verify a list of e-mails, or every stored e-mail for a company."""
    if not request.emails and request.company_id is None:
        raise HTTPException(
            status_code=422, detail="Provide 'emails' or 'company_id'"
        )
    if request.company_id is not None:
        _company_or_404(db, request.company_id)

    results = svc.verify_emails(
        db,
        company_id=request.company_id,
        emails=request.emails,
        smtp_enabled=settings.email_verify_smtp_enabled,
        catch_all_enabled=settings.email_verify_catch_all_enabled,
    )

    out = []
    for row, res in results:
        rs = rank_score(
            row.email,
            email_type=row.email_type,
            verification_status=row.verification_status,
            verification_score=row.verification_score,
            source=row.source,
        )
        item = _serialize(row, rs)
        item["catch_all"] = res.catch_all
        item["checks"] = res.checks
        out.append(item)
    return {"count": len(out), "results": out}


@router.get("/{company_id}", response_model=dict)
def list_emails(company_id: int, db: Session = Depends(get_db)):
    """List discovered e-mails for a company, ranked by discovery priority."""
    _company_or_404(db, company_id)
    rows = ecrud.list_by_company(db, company_id)
    return {
        "company_id": company_id,
        "count": len(rows),
        "emails": _enrich(rows),
    }
