"""CRUD operations for CompanyDocument (extracted PDF / brochure text)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.company_document import CompanyDocument


def create(
    db: Session,
    *,
    lead_id: int,
    url: str,
    file_type: Optional[str] = None,
    content: Optional[str] = None,
) -> CompanyDocument:
    obj = CompanyDocument(
        lead_id=lead_id, url=url, file_type=file_type, content=content
    )
    db.add(obj)
    db.flush()
    return obj


def get_by_lead(db: Session, lead_id: int) -> List[CompanyDocument]:
    return (
        db.query(CompanyDocument)
        .filter(CompanyDocument.lead_id == lead_id)
        .order_by(CompanyDocument.id.desc())
        .all()
    )


def get_by_url(db: Session, url: str) -> Optional[CompanyDocument]:
    return (
        db.query(CompanyDocument).filter(CompanyDocument.url == url).first()
    )
