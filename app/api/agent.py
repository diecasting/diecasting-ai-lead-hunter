"""AI Sales Agent API (Phase 9).

Router prefix ``/api/agent``. All endpoints are additive — they never call the
outreach send path, so the existing Outreach Engine / CRM behaviour is
untouched.

Endpoints
---------
  POST /api/agent/research/{company_id}        research brief (optional AI)
  POST /api/agent/draft/{company_id}           generate + persist an email draft
  POST /api/agent/personalize                  generate email only (no persist)
  GET  /api/agent/drafts/{company_id}          list drafts for a company
  GET  /api/agent/draft/{draft_id}             get a single draft
  PUT  /api/agent/draft/{draft_id}             edit a draft
  DELETE /api/agent/draft/{draft_id}           delete a draft
  POST /api/agent/quality                      score an arbitrary email
  POST /api/agent/draft/{draft_id}/score       re-score a stored draft
"""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai_sales_agent import service as svc
from app.ai_sales_agent.quality import score_email as svc_quality
from app.database import get_db
from app.models.lead import CompanyLead

router = APIRouter(prefix="/api/agent", tags=["ai-sales-agent"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------
class DraftRequest(BaseModel):
    contact_id: Optional[int] = None
    use_ai: bool = True
    tone: str = "professional"


class PersonalizeRequest(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    use_ai: bool = True
    tone: str = "professional"


class QualityRequest(BaseModel):
    subject: str = ""
    body: str = ""
    company: Optional[str] = None
    to_name: Optional[str] = None


class DraftUpdate(BaseModel):
    subject: Optional[str] = None
    opening: Optional[str] = None
    body: Optional[str] = None
    call_to_action: Optional[str] = None
    to_name: Optional[str] = None
    to_email: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _company_or_404(db: Session, company_id: int) -> CompanyLead:
    lead = db.query(CompanyLead).filter(CompanyLead.id == company_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return lead


def _serialize(draft) -> Dict:
    research = None
    if draft.research_summary:
        try:
            research = json.loads(draft.research_summary)
        except Exception:
            research = None
    return {
        "id": draft.id,
        "company_id": draft.company_id,
        "contact_id": draft.contact_id,
        "email_address_id": draft.email_address_id,
        "to_name": draft.to_name,
        "to_email": draft.to_email,
        "subject": draft.subject,
        "opening": draft.opening,
        "body": draft.body,
        "call_to_action": draft.call_to_action,
        "status": draft.status,
        "role_category": draft.role_category,
        "prompt_role": draft.prompt_role,
        "personalization_score": draft.personalization_score,
        "quality_score": draft.quality_score,
        "used_ai": draft.used_ai,
        "research": research,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/research/{company_id}")
def research_company(
    company_id: int,
    use_ai: bool = Query(False),
    db: Session = Depends(get_db),
):
    _company_or_404(db, company_id)
    research = svc.research_company(db, company_id, use_ai=use_ai)
    return research.to_dict() if research else {}


@router.post("/draft/{company_id}")
def create_draft(
    company_id: int,
    payload: DraftRequest,
    db: Session = Depends(get_db),
):
    _company_or_404(db, company_id)
    result = svc.generate_draft(
        db,
        company_id,
        contact_id=payload.contact_id,
        use_ai=payload.use_ai,
        tone=payload.tone,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    draft, _research = result
    return _serialize(draft)


@router.post("/personalize")
def personalize(payload: PersonalizeRequest, db: Session = Depends(get_db)):
    email = svc.personalize_only(
        db,
        payload.company_id,
        contact_id=payload.contact_id,
        use_ai=payload.use_ai,
        tone=payload.tone,
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return email


@router.get("/drafts/{company_id}")
def list_drafts(company_id: int, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    drafts = svc.list_drafts(db, company_id)
    return [_serialize(d) for d in drafts]


@router.get("/draft/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = svc.get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _serialize(draft)


@router.put("/draft/{draft_id}")
def update_draft(
    draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)
):
    fields = payload.model_dump(exclude_none=True)
    draft = svc.update_draft(db, draft_id, **fields)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _serialize(draft)


@router.delete("/draft/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    ok = svc.delete_draft(db, draft_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"deleted": True, "id": draft_id}


@router.post("/quality")
def score_email(payload: QualityRequest):
    score = svc_quality(
        payload.subject, payload.body,
        company=payload.company, to_name=payload.to_name,
    )
    return score.to_dict()


@router.post("/draft/{draft_id}/score")
def score_draft(draft_id: int, db: Session = Depends(get_db)):
    result = svc.score_draft(db, draft_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft, score = result
    data = _serialize(draft)
    data["quality_breakdown"] = score.to_dict()
    return data
