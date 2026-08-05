"""Outreach API routes — email generation and draft management."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.database import get_db
from app.outreach.email_generator import generate_email_from_lead
from app.schemas.outreach import (
    GenerateEmailRequest,
    OutreachMessageRead,
    ReviewGateRequest,
)

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get("/drafts", response_model=List[OutreachMessageRead])
def list_drafts(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    gate: Optional[str] = Query(
        None,
        pattern="^(ready|review|blocked)$",
        description="Filter by quality gate status: ready | review | blocked",
    ),
):
    """Return outreach messages in ``draft`` status, optionally filtered by gate."""
    return outreach_crud.list_drafts(db, skip=skip, limit=limit, gate=gate)


@router.patch("/drafts/{message_id}/gate", response_model=OutreachMessageRead)
def set_draft_gate(
    message_id: int,
    payload: ReviewGateRequest,
    db: Session = Depends(get_db),
):
    """Override the quality gate status for a draft (human reviewer release).

    A reviewer can release a ``review`` / ``blocked`` draft by setting it to
    ``ready``, or tighten a ``ready`` draft back to ``review`` / ``blocked``.
    """
    msg = outreach_crud.get(db, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return outreach_crud.set_gate_status(db, msg, payload.gate_status)


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
