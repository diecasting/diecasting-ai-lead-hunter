"""AI Outreach Campaign Engine API (Phase 9.5).

Router prefix ``/api/campaign``. All endpoints are additive — they operate on the
``campaigns`` / ``campaign_contacts`` tables and never call the outreach send
path, so the existing Outreach Engine / CRM / Contact Intelligence behaviour is
untouched.

Endpoints
---------
  POST   /api/campaign                          create a campaign
  GET    /api/campaign                          list campaigns
  GET    /api/campaign/{campaign_id}            get a campaign
  PUT    /api/campaign/{campaign_id}            update a campaign
  DELETE /api/campaign/{campaign_id}            delete a campaign
  POST   /api/campaign/{campaign_id}/targets    select + stage contacts
  GET    /api/campaign/{campaign_id}/contacts   list queue entries
  PUT    /api/campaign/{campaign_id}/contact/{cc_id}   update a queue entry
  POST   /api/campaign/{campaign_id}/generate   batch-generate drafts
  POST   /api/campaign/{campaign_id}/queue      stage ready -> queued (daily cap)
  GET    /api/campaign/{campaign_id}/stats      campaign analytics
  POST   /api/campaign/{campaign_id}/contact/{cc_id}/sent      record sent
  POST   /api/campaign/{campaign_id}/contact/{cc_id}/replied  record reply
  POST   /api/campaign/{campaign_id}/contact/{cc_id}/rfq      record RFQ
  POST   /api/campaign/{campaign_id}/contact/{cc_id}/bounced  record bounce
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.campaign import service as svc
from app.database import get_db
from app.models.campaign import (
    CC_STATUS_BOUNCED,
    CC_STATUS_REPLIED,
    CC_STATUS_RFQ,
    CC_STATUS_SENT,
    CC_STATUSES,
    Campaign,
    CampaignContact,
)


router = APIRouter(prefix="/api/campaign", tags=["campaign"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------
class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    target_industry: Optional[str] = None
    target_country: Optional[str] = None
    min_priority: Optional[str] = None
    min_sales_priority: Optional[str] = None
    daily_limit: int = 50
    quality_gate_min: Optional[int] = None
    use_ai: bool = True
    tone: str = "professional"
    status: str = "draft"


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_industry: Optional[str] = None
    target_country: Optional[str] = None
    min_priority: Optional[str] = None
    min_sales_priority: Optional[str] = None
    daily_limit: Optional[int] = None
    quality_gate_min: Optional[int] = None
    use_ai: Optional[bool] = None
    tone: Optional[str] = None
    status: Optional[str] = None


class TargetsRequest(BaseModel):
    max_per_company: int = 3
    quality_gate_min: Optional[int] = None


class GenerateRequest(BaseModel):
    use_ai: Optional[bool] = None
    tone: Optional[str] = None
    quality_gate_min: Optional[int] = None


class QueueRequest(BaseModel):
    daily_limit: Optional[int] = None
    as_of: Optional[str] = None  # ISO-8601; defaults to now (UTC)


class ContactUpdate(BaseModel):
    status: Optional[str] = None
    to_name: Optional[str] = None
    to_email: Optional[str] = None
    priority_rank: Optional[int] = None
    quality_score: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = svc.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _contact_or_404(db: Session, cc_id: int) -> CampaignContact:
    cc = svc.get_contact(db, cc_id)
    if cc is None:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    return cc


def _parse_as_of(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid as_of ISO timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_campaign(c: Campaign) -> Dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "target_industry": c.target_industry,
        "target_country": c.target_country,
        "min_priority": c.min_priority,
        "min_sales_priority": c.min_sales_priority,
        "daily_limit": c.daily_limit,
        "quality_gate_min": c.quality_gate_min,
        "use_ai": c.use_ai,
        "tone": c.tone,
        "status": c.status,
        "total_targets": c.total_targets,
        "sent_count": c.sent_count,
        "reply_count": c.reply_count,
        "rfq_count": c.rfq_count,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _serialize_contact(cc: CampaignContact) -> Dict:
    return {
        "id": cc.id,
        "campaign_id": cc.campaign_id,
        "company_id": cc.company_id,
        "contact_id": cc.contact_id,
        "email_address_id": cc.email_address_id,
        "draft_id": cc.draft_id,
        "company_name": cc.company_name,
        "to_name": cc.to_name,
        "to_email": cc.to_email,
        "status": cc.status,
        "priority_rank": cc.priority_rank,
        "quality_score": cc.quality_score,
        "sent_at": cc.sent_at,
        "replied_at": cc.replied_at,
        "rfq_at": cc.rfq_at,
        "created_at": cc.created_at,
        "updated_at": cc.updated_at,
    }


# ---------------------------------------------------------------------------
# Campaign lifecycle
# ---------------------------------------------------------------------------
@router.post("")
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = svc.create_campaign(
        db,
        name=payload.name,
        description=payload.description,
        target_industry=payload.target_industry,
        target_country=payload.target_country,
        min_priority=payload.min_priority,
        min_sales_priority=payload.min_sales_priority,
        daily_limit=payload.daily_limit,
        quality_gate_min=payload.quality_gate_min,
        use_ai=payload.use_ai,
        tone=payload.tone,
        status=payload.status,
    )
    return _serialize_campaign(campaign)


@router.get("")
def list_campaigns(db: Session = Depends(get_db)):
    return [_serialize_campaign(c) for c in svc.list_campaigns(db)]


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return _serialize_campaign(_campaign_or_404(db, campaign_id))


@router.put("/{campaign_id}")
def update_campaign(
    campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db)
):
    fields = payload.model_dump(exclude_none=True)
    campaign = svc.update_campaign(db, campaign_id, **fields)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _serialize_campaign(campaign)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    if not svc.delete_campaign(db, campaign_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"deleted": True, "id": campaign_id}


# ---------------------------------------------------------------------------
# Targeting + contacts
# ---------------------------------------------------------------------------
@router.post("/{campaign_id}/targets")
def build_targets(
    campaign_id: int, payload: TargetsRequest, db: Session = Depends(get_db)
):
    campaign = _campaign_or_404(db, campaign_id)
    added = svc.build_campaign_targets(
        db,
        campaign,
        max_per_company=payload.max_per_company,
        quality_gate_min=payload.quality_gate_min,
    )
    refreshed = svc.get_campaign(db, campaign_id)
    return {
        "campaign_id": campaign_id,
        "added": added,
        "total_targets": refreshed.total_targets,
    }


@router.get("/{campaign_id}/contacts")
def list_contacts(campaign_id: int, db: Session = Depends(get_db)):
    _campaign_or_404(db, campaign_id)
    return [_serialize_contact(cc) for cc in svc.list_contacts(db, campaign_id)]


@router.put("/{campaign_id}/contact/{cc_id}")
def update_contact(
    campaign_id: int, cc_id: int, payload: ContactUpdate,
    db: Session = Depends(get_db),
):
    _campaign_or_404(db, campaign_id)
    cc = _contact_or_404(db, cc_id)
    if cc.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    fields = payload.model_dump(exclude_none=True)
    if "status" in fields and fields["status"] not in CC_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Invalid status: {fields['status']}"
        )
    updated = svc.update_contact(db, cc_id, **fields)
    return _serialize_contact(updated)


# ---------------------------------------------------------------------------
# Batch draft generation + queue
# ---------------------------------------------------------------------------
@router.post("/{campaign_id}/generate")
def generate(
    campaign_id: int, payload: GenerateRequest, db: Session = Depends(get_db)
):
    _campaign_or_404(db, campaign_id)
    result = svc.generate_drafts(
        db,
        campaign_id,
        use_ai=payload.use_ai,
        tone=payload.tone,
        quality_gate_min=payload.quality_gate_min,
    )
    return result


@router.post("/{campaign_id}/queue")
def queue(
    campaign_id: int, payload: QueueRequest, db: Session = Depends(get_db)
):
    _campaign_or_404(db, campaign_id)
    as_of = _parse_as_of(payload.as_of)
    queued = svc.queue_ready_contacts(
        db, campaign_id, as_of=as_of, daily_limit=payload.daily_limit
    )
    return {"campaign_id": campaign_id, "queued": queued}


# ---------------------------------------------------------------------------
# Analytics + outcome recording
# ---------------------------------------------------------------------------
@router.get("/{campaign_id}/stats")
def stats(campaign_id: int, db: Session = Depends(get_db)):
    data = svc.campaign_stats(db, campaign_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return data


@router.post("/{campaign_id}/contact/{cc_id}/sent")
def mark_sent(campaign_id: int, cc_id: int, db: Session = Depends(get_db)):
    _campaign_or_404(db, campaign_id)
    cc = _contact_or_404(db, cc_id)
    if cc.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    return _serialize_contact(svc.mark_sent(db, cc_id))


@router.post("/{campaign_id}/contact/{cc_id}/replied")
def mark_replied(campaign_id: int, cc_id: int, db: Session = Depends(get_db)):
    _campaign_or_404(db, campaign_id)
    cc = _contact_or_404(db, cc_id)
    if cc.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    return _serialize_contact(svc.mark_replied(db, cc_id))


@router.post("/{campaign_id}/contact/{cc_id}/rfq")
def mark_rfq(campaign_id: int, cc_id: int, db: Session = Depends(get_db)):
    _campaign_or_404(db, campaign_id)
    cc = _contact_or_404(db, cc_id)
    if cc.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    return _serialize_contact(svc.mark_rfq(db, cc_id))


@router.post("/{campaign_id}/contact/{cc_id}/bounced")
def mark_bounced(campaign_id: int, cc_id: int, db: Session = Depends(get_db)):
    _campaign_or_404(db, campaign_id)
    cc = _contact_or_404(db, cc_id)
    if cc.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign contact not found")
    return _serialize_contact(svc.mark_bounced(db, cc_id))
