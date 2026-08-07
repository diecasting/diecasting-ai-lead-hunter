"""EmailDraft CRUD (Phase 9 AI Sales Agent).

Self-contained persistence helpers for the ``email_drafts`` table. These do not
touch the Outreach Engine's ``outreach_messages`` or the CRM, so the existing
send / engagement workflow is fully preserved.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.email_draft import (
    DRAFT_STATUS_DRAFT,
    EmailDraft,
)


def create(
    db: Session,
    *,
    company_id: int,
    subject: str,
    body: str,
    contact_id: Optional[int] = None,
    email_address_id: Optional[int] = None,
    to_name: Optional[str] = None,
    to_email: Optional[str] = None,
    opening: Optional[str] = None,
    call_to_action: Optional[str] = None,
    role_category: Optional[str] = None,
    prompt_role: Optional[str] = None,
    status: str = DRAFT_STATUS_DRAFT,
    research_summary: Optional[str] = None,
    used_ai: bool = False,
    personalization_score: Optional[int] = None,
    quality_score: Optional[int] = None,
) -> EmailDraft:
    """Insert a new draft row and return it."""
    obj = EmailDraft(
        company_id=company_id,
        contact_id=contact_id,
        email_address_id=email_address_id,
        to_name=to_name,
        to_email=to_email,
        subject=subject or "",
        opening=opening,
        body=body or "",
        call_to_action=call_to_action,
        status=status,
        role_category=role_category,
        prompt_role=prompt_role,
        research_summary=research_summary,
        used_ai=used_ai,
        personalization_score=personalization_score,
        quality_score=quality_score,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_by_company(db: Session, company_id: int) -> List[EmailDraft]:
    """All drafts for a company, newest first."""
    return (
        db.query(EmailDraft)
        .filter(EmailDraft.company_id == company_id)
        .order_by(EmailDraft.id.desc())
        .all()
    )


def get(db: Session, draft_id: int) -> Optional[EmailDraft]:
    return db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()


def update(db: Session, draft: EmailDraft, **fields) -> EmailDraft:
    """Update allowed fields on a draft and persist."""
    allowed = {
        "subject",
        "opening",
        "body",
        "call_to_action",
        "to_name",
        "to_email",
        "status",
        "role_category",
        "prompt_role",
        "research_summary",
        "used_ai",
        "personalization_score",
        "quality_score",
        "contact_id",
        "email_address_id",
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(draft, key, value)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def set_scores(
    db: Session,
    draft: EmailDraft,
    *,
    personalization_score: Optional[int] = None,
    quality_score: Optional[int] = None,
) -> EmailDraft:
    """Persist freshly computed scores."""
    if personalization_score is not None:
        draft.personalization_score = personalization_score
    if quality_score is not None:
        draft.quality_score = quality_score
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def delete(db: Session, draft_id: int) -> bool:
    obj = get(db, draft_id)
    if obj is None:
        return False
    db.delete(obj)
    db.commit()
    return True
