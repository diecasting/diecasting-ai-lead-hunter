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


def create(
    db: Session,
    *,
    obj_in: Optional[CompanyLeadCreate] = None,
    **fields,
) -> CompanyLead:
    """Create a lead from a schema OR from explicit column keyword arguments."""
    if obj_in is not None:
        data = obj_in.model_dump(exclude_unset=True)
    else:
        data = {}
    data.update(fields)
    db_obj = CompanyLead(**data)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(
    db: Session, *, db_obj: CompanyLead, obj_in: Optional[CompanyLeadUpdate] = None, **fields
) -> CompanyLead:
    if obj_in is not None:
        data = obj_in.model_dump(exclude_unset=True)
    else:
        data = {}
    data.update(fields)
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
    # The local SQLite dev DB does not enforce ON DELETE CASCADE, and the ORM's
    # default delete disassociates children by nulling their FK — which fails
    # for NOT NULL columns (e.g. outreach_messages.lead_id). Delete every FK
    # child explicitly first so a lead with related records can be removed.
    for rel in CompanyLead.__mapper__.relationships:
        if rel.direction.name != "ONETOMANY":
            continue
        child_cls = rel.mapper.class_
        child_fk_col = rel.local_remote_pairs[0][1]
        db.query(child_cls).filter(child_fk_col == lead_id).delete(
            synchronize_session=False
        )
    db.delete(obj)
    db.commit()
    return obj
