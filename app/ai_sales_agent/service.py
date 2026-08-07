"""AI Sales Agent service layer (Phase 9).

Orchestrates the agent's capabilities over the existing infrastructure:

  * company research briefs (``research``)
  * AI-personalised email generation (``personalization``, reusing the Outreach
    Engine baseline) + deterministic quality scoring (``quality``)
  * draft persistence + lifecycle (``crud``)

All functions take a SQLAlchemy ``Session`` and operate read-only on
``CompanyLead`` / ``Contact`` / ``EmailAddress``; they never call the outreach
send path, so the existing workflow is untouched.
"""
import json
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai_sales_agent import crud as draft_crud
from app.ai_sales_agent import personalization, quality, research as research_gen
from app.ai_sales_agent.quality import EmailQualityScore
from app.ai_sales_agent.research import CompanyResearch
from app.contact_intelligence.crud import get as get_contact, list_for_company
from app.email_discovery.crud import list_by_company as list_emails
from app.models.email_draft import DRAFT_STATUS_DRAFT, EmailDraft
from app.models.lead import CompanyLead


def _full_email_text(email: dict) -> str:
    """Concatenate the email parts into one body for quality scoring."""
    return "\n\n".join(
        p for p in (
            email.get("opening") or "",
            email.get("body") or "",
            email.get("call_to_action") or "",
        ) if p
    )


def generate_draft(
    db: Session,
    company_id: int,
    *,
    contact_id: Optional[int] = None,
    use_ai: bool = True,
    tone: str = "professional",
) -> Optional[Tuple[EmailDraft, CompanyResearch]]:
    """Generate, score and persist an email draft for a company (optionally a
    specific contact). Returns ``(EmailDraft, CompanyResearch)`` or ``None`` when
    the company does not exist.
    """
    lead = db.query(CompanyLead).filter(CompanyLead.id == company_id).first()
    if lead is None:
        return None

    contact = get_contact(db, contact_id) if contact_id is not None else None
    contacts = list_for_company(db, company_id)
    emails = list_emails(db, company_id)

    research = research_gen.generate_research(
        lead, db=db, contacts=contacts, emails=emails, use_ai=False
    )
    email = personalization.generate_email(
        lead, contact=contact, db=db, use_ai=use_ai, tone=tone
    )
    score: EmailQualityScore = quality.score_email(
        email.get("subject", ""),
        _full_email_text(email),
        company=lead.name,
        to_name=email.get("to_name"),
    )

    email_address_id = contact.email_address_id if contact else None

    draft = draft_crud.create(
        db,
        company_id=company_id,
        subject=email.get("subject", ""),
        body=email.get("body", ""),
        opening=email.get("opening"),
        call_to_action=email.get("call_to_action"),
        contact_id=contact.id if contact else None,
        email_address_id=email_address_id,
        to_name=email.get("to_name"),
        to_email=email.get("to_email"),
        role_category=email.get("role_category"),
        prompt_role=email.get("prompt_role"),
        status=DRAFT_STATUS_DRAFT,
        research_summary=json.dumps(research.to_dict(), ensure_ascii=False),
        used_ai=bool(email.get("used_ai")),
        personalization_score=score.personalization,
        quality_score=score.overall,
    )
    return draft, research


def research_company(
    db: Session, company_id: int, *, use_ai: bool = False
) -> Optional[CompanyResearch]:
    """Build (and optionally AI-enrich) a research brief for a company."""
    lead = db.query(CompanyLead).filter(CompanyLead.id == company_id).first()
    if lead is None:
        return None
    return research_gen.generate_research(
        lead,
        db=db,
        contacts=list_for_company(db, company_id),
        emails=list_emails(db, company_id),
        use_ai=use_ai,
    )


def personalize_only(
    db: Session,
    company_id: int,
    *,
    contact_id: Optional[int] = None,
    use_ai: bool = True,
    tone: str = "professional",
) -> Optional[dict]:
    """Generate a personalised email without persisting a draft."""
    lead = db.query(CompanyLead).filter(CompanyLead.id == company_id).first()
    if lead is None:
        return None
    contact = get_contact(db, contact_id) if contact_id is not None else None
    return personalization.generate_email(
        lead, contact=contact, db=db, use_ai=use_ai, tone=tone
    )


def list_drafts(db: Session, company_id: int) -> List[EmailDraft]:
    return draft_crud.list_by_company(db, company_id)


def get_draft(db: Session, draft_id: int) -> Optional[EmailDraft]:
    return draft_crud.get(db, draft_id)


def update_draft(db: Session, draft_id: int, **fields) -> Optional[EmailDraft]:
    draft = draft_crud.get(db, draft_id)
    if draft is None:
        return None
    return draft_crud.update(db, draft, **fields)


def delete_draft(db: Session, draft_id: int) -> bool:
    return draft_crud.delete(db, draft_id)


def score_draft(db: Session, draft_id: int) -> Optional[Tuple[EmailDraft, EmailQualityScore]]:
    """Recompute the quality + personalization scores for a stored draft."""
    draft = draft_crud.get(db, draft_id)
    if draft is None:
        return None
    full_text = "\n\n".join(
        p for p in (draft.opening or "", draft.body or "", draft.call_to_action or "") if p
    )
    score = quality.score_email(draft.subject or "", full_text, to_name=draft.to_name)
    draft_crud.set_scores(
        db,
        draft,
        personalization_score=score.personalization,
        quality_score=score.overall,
    )
    return draft, score
