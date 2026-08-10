"""Campaign service layer (Phase 9.5 AI Outreach Campaign Engine).

Orchestrates the campaign engine over the existing infrastructure:

  * target company filtering     -> CompanyLead (industry / country / priority)
  * contact selection + ranking  -> Contact Intelligence (deliverable contacts,
    ranked by purchasing signal + seniority)
  * duplicate prevention         -> de-dup by contact id + e-mail across the campaign
  * batch draft generation       -> reuses the AI Sales Agent (which itself reuses
    the Outreach Engine's deterministic baseline) + the quality gate
  * queue management             -> ready -> queued, capped by the daily limit
  * analytics                    -> sent / reply / RFQ / conversion from statuses

All functions take a SQLAlchemy ``Session`` and operate read-only on the
underlying tables; they never call the outreach send path, so the existing
workflow is untouched.
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai_sales_agent import crud as draft_crud
from app.ai_sales_agent import quality as draft_quality
from app.ai_sales_agent import service as agent_svc
from app.campaign import crud
from app.contact_intelligence.crud import get as get_contact_record
from app.contact_intelligence.crud import list_for_company
from app.contact_ranking import ContactRankingService
from app.models.email_draft import DRAFT_STATUS_DRAFT, EmailDraft
from app.outreach.personalization import (
    PersonalizationService as OutreachPersonalizationService,
)
from app.models.campaign import (
    CAMPAIGN_STATUS_ACTIVE,
    CC_SENT_STATUSES,
    CC_STATUS_QUEUED,
    CC_STATUS_READY,
    CC_STATUS_REJECTED,
    CC_STATUS_SELECTED,
    CC_STATUS_SENT,
    CC_STATUS_REPLIED,
    CC_STATUS_RFQ,
    CC_STATUS_BOUNCED,
    Campaign,
    CampaignContact,
)
from app.models.contact import Contact
from app.models.email_address import EmailAddress
from app.models.lead import CompanyLead

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority ranking helpers
# ---------------------------------------------------------------------------
_PRIORITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_SENIORITY_RANK = {
    "executive": 4, "senior": 3, "mid": 2, "junior": 1, "unknown": 0,
}

# Deliverability verdicts we consider safe to send to.
_DELIVERABLE = {"valid", "risky", "unknown", "unverified", None}


def _priority_rank(value: Optional[str]) -> int:
    return _PRIORITY_RANK.get((value or "").upper(), 0)


# ---------------------------------------------------------------------------
# Targeting — companies
# ---------------------------------------------------------------------------
def select_targets(
    db: Session,
    *,
    target_industry: Optional[str] = None,
    target_country: Optional[str] = None,
    min_priority: Optional[str] = None,
    min_sales_priority: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[CompanyLead]:
    """Return companies matching the campaign's targeting filters.

    Filters are AND-combined and all optional. ``do_not_contact`` companies are
    always excluded. Results are ordered by priority then lead score (best
    first).
    """
    query = db.query(CompanyLead)
    if target_industry:
        query = query.filter(CompanyLead.industry.ilike(f"%{target_industry}%"))
    if target_country:
        query = query.filter(CompanyLead.country.ilike(f"%{target_country}%"))
    if min_priority:
        min_rank = _priority_rank(min_priority)
        # SQL can't easily compare the textual priority, so fetch and filter.
        candidates = query.all()
        companies = [
            c for c in candidates
            if c.do_not_contact is not True
            and _priority_rank(c.priority) >= min_rank
        ]
    else:
        query = query.filter(
            (CompanyLead.do_not_contact.is_(None))
            | (CompanyLead.do_not_contact.is_(False))
        )
        companies = query.all()
        if min_sales_priority:
            min_rank = _priority_rank(min_sales_priority)
            companies = [
                c for c in companies
                if _priority_rank(c.sales_priority) >= min_rank
            ]

    companies = rank_companies(companies)
    if limit is not None:
        companies = companies[:limit]
    return companies


def rank_companies(companies: List[CompanyLead]) -> List[CompanyLead]:
    """Order companies best-first (priority, then lead score)."""
    def _key(c: CompanyLead):
        prio = max(_priority_rank(c.priority), _priority_rank(c.sales_priority))
        score = c.lead_score or 0
        return (prio, score)
    return sorted(companies, key=_key, reverse=True)


# ---------------------------------------------------------------------------
# Targeting — contacts
# ---------------------------------------------------------------------------
def _contact_sort_key(contact: Contact):
    """Lower tuple sorts first.

    Phase 14.1.1: when a deterministic ``ranking_score`` has been computed for
    the contact (via ``ContactRankingService``) it is the primary sort key and
    always precedes contacts that have not been ranked yet. Contacts without
    ranking data fall back to the legacy procurement / purchasing-score /
    seniority ordering, so selection is backward-compatible.
    """
    rs = getattr(contact, "ranking_score", None)
    if rs is not None:
        return (0, -rs)
    procurement_first = 0 if (contact.title_category or "") == "procurement" else 1
    score = contact.purchasing_score or 0
    seniority = _SENIORITY_RANK.get((contact.seniority or "").lower(), 0)
    return (1, procurement_first, -score, -seniority)


def _is_deliverable(db: Session, contact: Contact) -> bool:
    """A contact is deliverable when it has an e-mail and that e-mail is not a
    known hard-bounce / invalid address."""
    if not contact.email:
        return False
    if contact.email_address_id is not None:
        addr = (
            db.query(EmailAddress)
            .filter(EmailAddress.id == contact.email_address_id)
            .first()
        )
        if addr is not None and addr.verification_status == "invalid":
            return False
    return True


def select_contacts(
    db: Session,
    company_id: int,
    *,
    quality_gate_min: Optional[int] = None,
) -> List[Contact]:
    """Return ranked, deliverable contacts for a company (best first)."""
    contacts = list_for_company(db, company_id)
    eligible = [
        c for c in contacts
        if c.do_not_contact is not True and _is_deliverable(db, c)
    ]
    eligible.sort(key=_contact_sort_key)
    return eligible


# ---------------------------------------------------------------------------
# Build campaign targets (selection + ranking + duplicate prevention)
# ---------------------------------------------------------------------------
def build_campaign_targets(
    db: Session,
    campaign: Campaign,
    *,
    max_per_company: int = 3,
    quality_gate_min: Optional[int] = None,
) -> int:
    """Select + rank contacts for the campaign's target companies and stage them
    as ``selected`` queue entries.

    Duplicate prevention: a contact (by id) or e-mail is added to a campaign at
    most once — across companies too (so the same person at sibling companies is
    not mailed twice). Returns the number of new entries created.
    """
    companies = select_targets(
        db,
        target_industry=campaign.target_industry,
        target_country=campaign.target_country,
        min_priority=campaign.min_priority,
        min_sales_priority=campaign.min_sales_priority,
    )

    existing = crud.list_contacts(db, campaign.id)
    seen_contact_ids = {c.contact_id for c in existing if c.contact_id}
    seen_emails = {
        (c.to_email or "").lower() for c in existing if c.to_email
    }

    added = 0
    rank = 0
    for company in companies:
        # Phase 14.1.1: compute the deterministic outreach ranking for this
        # company's contacts *before* selection. The ranking engine is the
        # producer of ``Contact.ranking_score``; wiring it here makes the
        # campaign engine consume that score. A ranking failure is isolated so
        # it degrades gracefully to the legacy ordering instead of aborting the
        # whole campaign build.
        try:
            ContactRankingService(db).rank_company_contacts(company.id)
        except Exception:
            logger.warning(
                "contact_ranking_failed",
                extra={"company_id": company.id},
                exc_info=True,
            )
        contacts = select_contacts(
            db, company.id, quality_gate_min=quality_gate_min
        )
        per_company = 0
        for contact in contacts:
            if per_company >= max_per_company:
                break
            email = (contact.email or "").lower()
            if contact.id in seen_contact_ids or (
                email and email in seen_emails
            ):
                continue  # de-duplicate by contact id + e-mail
            seen_contact_ids.add(contact.id)
            if email:
                seen_emails.add(email)
            rank += 1
            crud.add_contact(
                db,
                campaign_id=campaign.id,
                company_id=company.id,
                contact_id=contact.id,
                email_address_id=contact.email_address_id,
                company_name=company.name,
                to_name=contact.full_name or contact.first_name,
                to_email=contact.email,
                status=CC_STATUS_SELECTED,
                priority_rank=rank,
            )
            per_company += 1
            added += 1

    crud._recompute_campaign_counters(db, campaign.id)
    return added


# ---------------------------------------------------------------------------
# Batch draft generation (reuse AI Sales Agent + quality gate)
# ---------------------------------------------------------------------------
def _try_personalized_draft(
    db: Session,
    company_id: int,
    *,
    contact_id: Optional[int] = None,
    tone: Optional[str] = None,
) -> Optional[EmailDraft]:
    """Attempt a deterministic personalized draft via ``PersonalizationService``.

    Returns an :class:`~app.models.email_draft.EmailDraft` on success, or
    ``None`` to signal the caller should fall back to the existing AI Sales
    Agent draft path. Any exception inside the personalization layer is an
    internal failure and must NOT abort campaign generation — it is logged and
    swallowed here so draft creation (and therefore the campaign build) proceeds
    via the fallback.
    """
    try:
        lead = (
            db.query(CompanyLead)
            .filter(CompanyLead.id == company_id)
            .first()
        )
        if lead is None:
            return None
        contact = get_contact_record(db, contact_id) if contact_id is not None else None

        svc = OutreachPersonalizationService(db)
        email = svc.personalize(lead, contact)
        if email is None:
            return None

        # Pull recipient identifiers off the contact when present.
        to_name = to_email = email_address_id = role_category = prompt_role = None
        if contact is not None:
            to_name = contact.full_name or contact.first_name
            to_email = contact.email
            email_address_id = contact.email_address_id
            role_category = contact.title_category
            prompt_role = contact.role

        # Score the personalized copy with the same deterministic quality scorer
        # the AI Sales Agent uses, so the quality gate treats it identically.
        score = draft_quality.score_email(
            email.subject, email.body, company=lead.name, to_name=to_name
        )

        draft = draft_crud.create(
            db,
            company_id=company_id,
            subject=email.subject,
            body=email.body,
            contact_id=contact.id if contact is not None else None,
            email_address_id=email_address_id,
            to_name=to_name,
            to_email=to_email,
            role_category=role_category,
            prompt_role=prompt_role,
            status=DRAFT_STATUS_DRAFT,
            research_summary=json.dumps(
                {
                    "source": "personalization_service",
                    "personalization_score": email.personalization_score,
                    "personalization_reason": email.personalization_reason,
                },
                ensure_ascii=False,
            ),
            used_ai=False,
            personalization_score=email.personalization_score,
            quality_score=score.overall,
        )
        return draft
    except Exception:
        logger.warning(
            "personalization_failed",
            extra={"company_id": company_id, "contact_id": contact_id},
            exc_info=True,
        )
        return None


def _generate_contact_draft(
    db: Session,
    company_id: int,
    *,
    contact_id: Optional[int] = None,
    use_ai: bool = False,
    tone: Optional[str] = None,
) -> Optional[EmailDraft]:
    """Produce an email draft for one campaign contact.

    Phase 14.2.1 wiring: in the deterministic (non-AI) mode the outreach
    preparation flow first tries :class:`PersonalizationService` to render a
    context-rich, ranking-aware draft (the producer of the *personalized*
    subject / body). If that fails for any reason we fall back to the existing
    AI Sales Agent draft path (its deterministic baseline) so campaign creation
    is never blocked. The AI path (``use_ai=True``) keeps using the agent
    unchanged.
    """
    if not use_ai:
        personalized = _try_personalized_draft(
            db, company_id, contact_id=contact_id, tone=tone
        )
        if personalized is not None:
            return personalized
    result = agent_svc.generate_draft(
        db, company_id, contact_id=contact_id, use_ai=use_ai, tone=tone
    )
    if result is None:
        return None
    draft, _research = result
    return draft


def generate_drafts(
    db: Session,
    campaign_id: int,
    *,
    use_ai: Optional[bool] = None,
    tone: Optional[str] = None,
    quality_gate_min: Optional[int] = None,
) -> Dict:
    """Generate a personalised draft for every ``selected`` queue entry.

    Reuses ``app.ai_sales_agent.service.generate_draft`` (which itself reuses the
    Outreach Engine's deterministic baseline) — no generation logic is
    duplicated here. Drafts that fall below the quality gate are marked
    ``rejected``; the rest become ``ready``.
    """
    campaign = crud.get_campaign(db, campaign_id)
    if campaign is None:
        return {}
    use_ai = campaign.use_ai if use_ai is None else use_ai
    tone = campaign.tone if tone is None else tone
    gate = quality_gate_min if quality_gate_min is not None else campaign.quality_gate_min

    contacts = crud.list_contacts(db, campaign_id)
    selected = [c for c in contacts if c.status == CC_STATUS_SELECTED]

    generated = passed = rejected = 0
    for cc in selected:
        if cc.company_id is None:
            continue
        draft = _generate_contact_draft(
            db,
            cc.company_id,
            contact_id=cc.contact_id,
            use_ai=use_ai,
            tone=tone,
        )
        if draft is None:
            continue
        generated += 1
        cc.draft_id = draft.id
        cc.quality_score = draft.quality_score
        if gate is not None and (draft.quality_score or 0) < gate:
            cc.status = CC_STATUS_REJECTED
        else:
            cc.status = CC_STATUS_READY
            passed += 1
        db.add(cc)
        db.commit()
        db.refresh(cc)
        if cc.status == CC_STATUS_REJECTED:
            rejected += 1

    crud._recompute_campaign_counters(db, campaign_id)
    return {
        "selected": len(selected),
        "generated": generated,
        "passed": passed,
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# Queue management (daily sending limit)
# ---------------------------------------------------------------------------
def _sent_or_queued_today(
    db: Session, campaign_id: int, as_of: datetime
) -> int:
    """Count contacts already committed against today's cap (sent + queued)."""
    contacts = crud.list_contacts(db, campaign_id)
    day = as_of.date() if isinstance(as_of, datetime) else as_of
    count = 0
    for c in contacts:
        if c.status == CC_STATUS_QUEUED:
            count += 1
        elif c.status in CC_SENT_STATUSES and c.sent_at is not None:
            if c.sent_at.date() == day:
                count += 1
    return count


def queue_ready_contacts(
    db: Session,
    campaign_id: int,
    *,
    as_of: Optional[datetime] = None,
    daily_limit: Optional[int] = None,
) -> int:
    """Stage ``ready`` contacts as ``queued`` for sending, respecting the daily
    limit. Returns the number newly queued today."""
    campaign = crud.get_campaign(db, campaign_id)
    if campaign is None:
        return 0
    when = as_of or datetime.now(timezone.utc)
    limit = daily_limit if daily_limit is not None else campaign.daily_limit

    committed = _sent_or_queued_today(db, campaign_id, when)
    remaining = max(0, limit - committed)
    if remaining == 0:
        return 0

    contacts = crud.list_contacts(db, campaign_id)
    ready = [c for c in contacts if c.status == CC_STATUS_READY]
    queued = 0
    for cc in ready:
        if queued >= remaining:
            break
        crud.update_contact_status(db, cc, CC_STATUS_QUEUED, as_of=when)
        queued += 1
    return queued


# ---------------------------------------------------------------------------
# Outcome recording (analytics)
# ---------------------------------------------------------------------------
def mark_sent(db: Session, campaign_contact_id: int,
              as_of: Optional[datetime] = None) -> Optional[CampaignContact]:
    cc = crud.get_contact(db, campaign_contact_id)
    if cc is None:
        return None
    return crud.update_contact_status(db, cc, CC_STATUS_SENT, as_of=as_of)


def mark_replied(db: Session, campaign_contact_id: int,
                 as_of: Optional[datetime] = None) -> Optional[CampaignContact]:
    cc = crud.get_contact(db, campaign_contact_id)
    if cc is None:
        return None
    return crud.update_contact_status(db, cc, CC_STATUS_REPLIED, as_of=as_of)


def mark_rfq(db: Session, campaign_contact_id: int,
             as_of: Optional[datetime] = None) -> Optional[CampaignContact]:
    cc = crud.get_contact(db, campaign_contact_id)
    if cc is None:
        return None
    return crud.update_contact_status(db, cc, CC_STATUS_RFQ, as_of=as_of)


def mark_bounced(db: Session, campaign_contact_id: int,
                 as_of: Optional[datetime] = None) -> Optional[CampaignContact]:
    cc = crud.get_contact(db, campaign_contact_id)
    if cc is None:
        return None
    return crud.update_contact_status(db, cc, CC_STATUS_BOUNCED, as_of=as_of)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def campaign_stats(db: Session, campaign_id: int) -> Optional[Dict]:
    """Aggregate campaign analytics from the queue statuses.

    Returns ``None`` when the campaign does not exist. Conversion = RFQ / sent;
    reply rate = replied(+rfq) / sent.
    """
    campaign = crud.get_campaign(db, campaign_id)
    if campaign is None:
        return None
    contacts = crud.list_contacts(db, campaign_id)

    by_status: Dict[str, int] = {}
    for c in contacts:
        by_status[c.status] = by_status.get(c.status, 0) + 1

    sent = sum(by_status.get(s, 0) for s in CC_SENT_STATUSES)
    replied = by_status.get(CC_STATUS_REPLIED, 0) + by_status.get(CC_STATUS_RFQ, 0)
    rfq = by_status.get(CC_STATUS_RFQ, 0)

    conversion = round(rfq / sent, 4) if sent else 0.0
    reply_rate = round(replied / sent, 4) if sent else 0.0

    return {
        "campaign_id": campaign_id,
        "name": campaign.name,
        "status": campaign.status,
        "total_targets": len(contacts),
        "by_status": by_status,
        "sent": sent,
        "replied": replied,
        "rfq": rfq,
        "reply_rate": reply_rate,
        "conversion": conversion,
        "daily_limit": campaign.daily_limit,
    }


# ---------------------------------------------------------------------------
# Thin CRUD wrappers (campaign lifecycle)
# ---------------------------------------------------------------------------
def create_campaign(db: Session, **fields) -> Campaign:
    return crud.create_campaign(db, **fields)


def get_campaign(db: Session, campaign_id: int) -> Optional[Campaign]:
    return crud.get_campaign(db, campaign_id)


def get_contact(db: Session, campaign_contact_id: int) -> Optional[CampaignContact]:
    return crud.get_contact(db, campaign_contact_id)


def list_contacts(db: Session, campaign_id: int) -> List[CampaignContact]:
    return crud.list_contacts(db, campaign_id)


def list_campaigns(db: Session) -> List[Campaign]:
    return crud.list_campaigns(db)


def update_campaign(db: Session, campaign_id: int, **fields) -> Optional[Campaign]:
    campaign = crud.get_campaign(db, campaign_id)
    if campaign is None:
        return None
    return crud.update_campaign(db, campaign, **fields)


def delete_campaign(db: Session, campaign_id: int) -> bool:
    return crud.delete_campaign(db, campaign_id)


def activate_campaign(db: Session, campaign_id: int) -> Optional[Campaign]:
    return update_campaign(db, campaign_id, status=CAMPAIGN_STATUS_ACTIVE)
