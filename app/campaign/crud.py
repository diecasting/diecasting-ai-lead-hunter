"""Campaign CRUD (Phase 9.5 AI Outreach Campaign Engine).

Self-contained persistence helpers for the ``campaigns`` and
``campaign_contacts`` tables. These do not touch the Outreach Engine's
``outreach_messages`` or the CRM, so the existing send / engagement workflow is
fully preserved.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.campaign import (
    CAMPAIGN_STATUS_DRAFT,
    CC_SENT_STATUSES,
    Campaign,
    CampaignContact,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
def create_campaign(
    db: Session,
    *,
    name: str,
    description: Optional[str] = None,
    target_industry: Optional[str] = None,
    target_country: Optional[str] = None,
    min_priority: Optional[str] = None,
    min_sales_priority: Optional[str] = None,
    daily_limit: int = 50,
    quality_gate_min: Optional[int] = None,
    use_ai: bool = True,
    tone: str = "professional",
    status: str = CAMPAIGN_STATUS_DRAFT,
) -> Campaign:
    obj = Campaign(
        name=name,
        description=description,
        target_industry=target_industry,
        target_country=target_country,
        min_priority=min_priority,
        min_sales_priority=min_sales_priority,
        daily_limit=daily_limit,
        quality_gate_min=quality_gate_min,
        use_ai=use_ai,
        tone=tone,
        status=status,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_campaign(db: Session, campaign_id: int) -> Optional[Campaign]:
    return db.query(Campaign).filter(Campaign.id == campaign_id).first()


def list_campaigns(db: Session) -> List[Campaign]:
    return db.query(Campaign).order_by(Campaign.id.desc()).all()


_ALLOWED_CAMPAIGN_FIELDS = {
    "name", "description", "target_industry", "target_country",
    "min_priority", "min_sales_priority", "daily_limit", "quality_gate_min",
    "use_ai", "tone", "status",
}


def update_campaign(db: Session, campaign: Campaign, **fields) -> Campaign:
    for key, value in fields.items():
        if key in _ALLOWED_CAMPAIGN_FIELDS:
            setattr(campaign, key, value)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def delete_campaign(db: Session, campaign_id: int) -> bool:
    obj = get_campaign(db, campaign_id)
    if obj is None:
        return False
    db.delete(obj)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Campaign contacts (the queue)
# ---------------------------------------------------------------------------
def add_contact(
    db: Session,
    *,
    campaign_id: int,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    email_address_id: Optional[int] = None,
    draft_id: Optional[int] = None,
    company_name: Optional[str] = None,
    to_name: Optional[str] = None,
    to_email: Optional[str] = None,
    status: str = "selected",
    priority_rank: Optional[int] = None,
    quality_score: Optional[int] = None,
) -> CampaignContact:
    obj = CampaignContact(
        campaign_id=campaign_id,
        company_id=company_id,
        contact_id=contact_id,
        email_address_id=email_address_id,
        draft_id=draft_id,
        company_name=company_name,
        to_name=to_name,
        to_email=to_email,
        status=status,
        priority_rank=priority_rank,
        quality_score=quality_score,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_contacts(db: Session, campaign_id: int) -> List[CampaignContact]:
    return (
        db.query(CampaignContact)
        .filter(CampaignContact.campaign_id == campaign_id)
        .order_by(CampaignContact.priority_rank.asc(), CampaignContact.id.asc())
        .all()
    )


def get_contact(db: Session, campaign_contact_id: int) -> Optional[CampaignContact]:
    return (
        db.query(CampaignContact)
        .filter(CampaignContact.id == campaign_contact_id)
        .first()
    )


_ALLOWED_CC_FIELDS = {
    "company_id", "contact_id", "email_address_id", "draft_id",
    "company_name", "to_name", "to_email", "status", "priority_rank",
    "quality_score", "sent_at", "replied_at", "rfq_at",
}


def update_contact(
    db: Session, cc: CampaignContact, **fields
) -> CampaignContact:
    for key, value in fields.items():
        if key in _ALLOWED_CC_FIELDS and value is not None:
            setattr(cc, key, value)
    db.add(cc)
    db.commit()
    db.refresh(cc)
    return cc


def update_contact_status(
    db: Session,
    cc: CampaignContact,
    status: str,
    *,
    as_of: Optional[datetime] = None,
) -> CampaignContact:
    """Transition a queue entry's status and keep campaign counters in sync.

    Sets the appropriate analytics timestamp and recomputes the cached
    ``sent_count`` / ``reply_count`` / ``rfq_count`` counters on the parent
    campaign from its contacts (robust against double-counting).
    """
    cc.status = status
    when = as_of or _utcnow()
    if status == "sent" and cc.sent_at is None:
        cc.sent_at = when
    elif status == "replied" and cc.replied_at is None:
        cc.replied_at = when
        if cc.sent_at is None:
            cc.sent_at = when
    elif status == "rfq" and cc.rfq_at is None:
        cc.rfq_at = when
        if cc.sent_at is None:
            cc.sent_at = when
    db.add(cc)
    db.commit()
    db.refresh(cc)
    _recompute_campaign_counters(db, cc.campaign_id)
    db.refresh(cc)
    return cc


def remove_contact(db: Session, campaign_contact_id: int) -> bool:
    obj = get_contact(db, campaign_contact_id)
    if obj is None:
        return False
    db.delete(obj)
    db.commit()
    _recompute_campaign_counters(db, obj.campaign_id)
    return True


def _recompute_campaign_counters(db: Session, campaign_id: int) -> None:
    """Recompute ``total_targets`` + analytics counters from the queue rows."""
    campaign = get_campaign(db, campaign_id)
    if campaign is None:
        return
    contacts = list_contacts(db, campaign_id)
    campaign.total_targets = len(contacts)
    campaign.sent_count = sum(1 for c in contacts if c.status in CC_SENT_STATUSES)
    campaign.reply_count = sum(1 for c in contacts if c.status in ("replied", "rfq"))
    campaign.rfq_count = sum(1 for c in contacts if c.status == "rfq")
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
