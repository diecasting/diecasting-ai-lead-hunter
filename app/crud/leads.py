"""CRUD operations for CompanyLead."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.lead import CompanyLead
from app.schemas.lead import CompanyLeadCreate, CompanyLeadUpdate


def get(db: Session, lead_id: int) -> Optional[CompanyLead]:
    return db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()


def get_by_website(db: Session, website: str) -> Optional[CompanyLead]:
    return db.query(CompanyLead).filter(CompanyLead.website == website).first()


def get_multi(
    db: Session, *, skip: int = 0, limit: int = 100, relevant_only: bool = False
) -> List[CompanyLead]:
    query = db.query(CompanyLead)
    if relevant_only:
        query = query.filter(CompanyLead.ai_relevant.is_(True))
    return query.order_by(CompanyLead.id.desc()).offset(skip).limit(limit).all()


def create(db: Session, *, obj_in: CompanyLeadCreate) -> CompanyLead:
    db_obj = CompanyLead(
        name=obj_in.name,
        website=obj_in.website,
        domain=obj_in.domain,
        country=obj_in.country,
        region=obj_in.region,
        industry=obj_in.industry,
        description=obj_in.description,
        employee_count=obj_in.employee_count,
        contact_email=obj_in.contact_email,
        contact_phone=obj_in.contact_phone,
        source=obj_in.source,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(
    db: Session, *, db_obj: CompanyLead, obj_in: CompanyLeadUpdate
) -> CompanyLead:
    data = obj_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def remove(db: Session, *, lead_id: int) -> Optional[CompanyLead]:
    obj = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    if obj is None:
        return None
    db.delete(obj)
    db.commit()
    return obj
