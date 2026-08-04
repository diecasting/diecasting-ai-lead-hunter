"""Phase 3 Stage 1 CRM data-model API.

REST CRUD for the six new tables: contacts, lead_sources, email_verifications,
email_tracking, reply_inbox, unsubscribes. (Aggregate CRM pipeline endpoints
remain in app/api/crm.py.)

All routes are prefixed ``/crm-data`` to avoid colliding with the existing
``/crm`` pipeline routes.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud import (
    contacts as contacts_crud,
    email_tracking as email_tracking_crud,
    email_verifications as email_verifications_crud,
    lead_sources as lead_sources_crud,
    reply_inbox as reply_inbox_crud,
    unsubscribes as unsubscribes_crud,
)
from app.database import get_db
from app.schemas import crm as schemas

router = APIRouter(prefix="/crm-data", tags=["crm-data"])


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
@router.post("/contacts", response_model=schemas.ContactRead, status_code=201)
def create_contact(payload: schemas.ContactCreate, db: Session = Depends(get_db)):
    return contacts_crud.create(db, lead_id=payload.lead_id, **payload.model_dump(exclude={"lead_id"}))


@router.get("/contacts/{contact_id}", response_model=schemas.ContactRead)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    obj = contacts_crud.get(db, contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return obj


@router.get("/leads/{lead_id}/contacts", response_model=List[schemas.ContactRead])
def list_contacts_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return contacts_crud.list_for_lead(db, lead_id)


@router.patch("/contacts/{contact_id}", response_model=schemas.ContactRead)
def update_contact(contact_id: int, payload: schemas.ContactUpdate, db: Session = Depends(get_db)):
    obj = contacts_crud.get(db, contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contacts_crud.update(db, obj, **payload.model_dump(exclude_unset=True))


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    obj = contacts_crud.get(db, contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    contacts_crud.delete(db, obj)


# ---------------------------------------------------------------------------
# Lead sources
# ---------------------------------------------------------------------------
@router.post("/lead-sources", response_model=schemas.LeadSourceRead, status_code=201)
def create_lead_source(payload: schemas.LeadSourceCreate, db: Session = Depends(get_db)):
    if lead_sources_crud.get_by_name(db, payload.name):
        raise HTTPException(status_code=409, detail="Lead source name already exists")
    return lead_sources_crud.create(db, name=payload.name, **payload.model_dump(exclude={"name"}))


@router.get("/lead-sources", response_model=List[schemas.LeadSourceRead])
def list_lead_sources(
    db: Session = Depends(get_db), active_only: bool = Query(False)
):
    return lead_sources_crud.list_all(db, active_only=active_only)


@router.get("/lead-sources/{source_id}", response_model=schemas.LeadSourceRead)
def get_lead_source(source_id: int, db: Session = Depends(get_db)):
    obj = lead_sources_crud.get(db, source_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead source not found")
    return obj


@router.patch("/lead-sources/{source_id}", response_model=schemas.LeadSourceRead)
def update_lead_source(source_id: int, payload: schemas.LeadSourceUpdate, db: Session = Depends(get_db)):
    obj = lead_sources_crud.get(db, source_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead source not found")
    return lead_sources_crud.update(db, obj, **payload.model_dump(exclude_unset=True))


@router.delete("/lead-sources/{source_id}", status_code=204)
def delete_lead_source(source_id: int, db: Session = Depends(get_db)):
    obj = lead_sources_crud.get(db, source_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead source not found")
    lead_sources_crud.delete(db, obj)


# ---------------------------------------------------------------------------
# Email verifications
# ---------------------------------------------------------------------------
@router.post("/email-verifications", response_model=schemas.EmailVerificationRead, status_code=201)
def create_email_verification(payload: schemas.EmailVerificationCreate, db: Session = Depends(get_db)):
    return email_verifications_crud.create(db, email=payload.email, **payload.model_dump(exclude={"email"}))


@router.get("/email-verifications/{verification_id}", response_model=schemas.EmailVerificationRead)
def get_email_verification(verification_id: int, db: Session = Depends(get_db)):
    obj = email_verifications_crud.get(db, verification_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Email verification not found")
    return obj


@router.get("/leads/{lead_id}/email-verifications", response_model=List[schemas.EmailVerificationRead])
def list_email_verifications_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return email_verifications_crud.list_for_lead(db, lead_id)


# ---------------------------------------------------------------------------
# Email tracking
# ---------------------------------------------------------------------------
@router.post("/email-tracking", response_model=schemas.EmailTrackingRead, status_code=201)
def create_email_tracking(payload: schemas.EmailTrackingCreate, db: Session = Depends(get_db)):
    if payload.event_type not in ("open", "click"):
        raise HTTPException(status_code=400, detail="event_type must be 'open' or 'click'")
    return email_tracking_crud.create(
        db, message_id=payload.message_id, event_type=payload.event_type,
        **payload.model_dump(exclude={"message_id", "event_type"})
    )


@router.get("/email-tracking/{tracking_id}", response_model=schemas.EmailTrackingRead)
def get_email_tracking(tracking_id: int, db: Session = Depends(get_db)):
    obj = email_tracking_crud.get(db, tracking_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Email tracking event not found")
    return obj


@router.get("/messages/{message_id}/email-tracking", response_model=List[schemas.EmailTrackingRead])
def list_email_tracking_for_message(message_id: int, db: Session = Depends(get_db)):
    return email_tracking_crud.list_for_message(db, message_id)


# ---------------------------------------------------------------------------
# Reply inbox
# ---------------------------------------------------------------------------
@router.post("/reply-inbox", response_model=schemas.ReplyInboxRead, status_code=201)
def create_reply(payload: schemas.ReplyInboxCreate, db: Session = Depends(get_db)):
    return reply_inbox_crud.create(db, **payload.model_dump())


@router.get("/reply-inbox", response_model=List[schemas.ReplyInboxRead])
def list_replies(
    db: Session = Depends(get_db),
    bounces_only: bool = Query(False),
    lead_id: Optional[int] = Query(None),
):
    if lead_id is not None:
        return reply_inbox_crud.list_for_lead(db, lead_id)
    return reply_inbox_crud.list_all(db, bounces_only=bounces_only)


@router.get("/reply-inbox/{reply_id}", response_model=schemas.ReplyInboxRead)
def get_reply(reply_id: int, db: Session = Depends(get_db)):
    obj = reply_inbox_crud.get(db, reply_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Reply not found")
    return obj


# ---------------------------------------------------------------------------
# Unsubscribes
# ---------------------------------------------------------------------------
@router.post("/unsubscribes", response_model=schemas.UnsubscribeRead, status_code=201)
def create_unsubscribe(payload: schemas.UnsubscribeCreate, db: Session = Depends(get_db)):
    return unsubscribes_crud.create(db, **payload.model_dump())


@router.get("/unsubscribes/{unsubscribe_id}", response_model=schemas.UnsubscribeRead)
def get_unsubscribe(unsubscribe_id: int, db: Session = Depends(get_db)):
    obj = unsubscribes_crud.get(db, unsubscribe_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Unsubscribe not found")
    return obj


@router.get("/leads/{lead_id}/unsubscribes", response_model=List[schemas.UnsubscribeRead])
def list_unsubscribes_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return unsubscribes_crud.list_for_lead(db, lead_id)
