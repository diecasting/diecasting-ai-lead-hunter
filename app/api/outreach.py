"""Outreach API routes — email generation and draft management."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.database import get_db
from app.outreach.email_generator import generate_email_from_lead
from app.schemas.outreach import GenerateEmailRequest, OutreachMessageRead

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get("/drafts", response_model=List[OutreachMessageRead])
def list_drafts(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Return all outreach messages currently in ``draft`` status."""
    return outreach_crud.list_drafts(db, skip=skip, limit=limit)


@router.get("/leads/{lead_id}/messages", response_model=List[OutreachMessageRead])
def get_lead_messages(
    lead_id: int,
    db: Session = Depends(get_db),
    status: str = Query(None, description="Filter by status: draft/approved/sent/replied"),
):
    """Return all outreach messages for a specific lead."""
    lead = leads_crud.get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return outreach_crud.get_by_lead(db, lead_id, status=status)
