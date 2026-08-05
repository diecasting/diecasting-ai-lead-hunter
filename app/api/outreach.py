"""Outreach API routes — email generation and draft management."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.crud import outreach_events as events_crud
from app.database import get_db
from app.outreach.email_generator import generate_email_from_lead
from app.outreach.sender import get_email_sender
from app.schemas.outreach import (
    GenerateEmailRequest,
    OutreachMessageRead,
    ReviewGateRequest,
    SendDraftResponse,
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


@router.post("/drafts/{message_id}/send", response_model=SendDraftResponse)
def send_draft(
    message_id: int,
    db: Session = Depends(get_db),
):
    """Send an approved outreach draft (Phase 4 Stage 5 sending pipeline).

    Rules:
      * only drafts with ``quality_gate_status == "ready"`` can be sent;
        ``review`` and ``blocked`` drafts are rejected with 422.
      * ``recipient_email`` is required — a missing or malformed address
        returns a 422 validation error.
      * delivery goes through the configured SMTP provider
        (``SMTP_HOST``/``SMTP_PORT``/``SMTP_USERNAME``/``SMTP_PASSWORD``/
        ``SMTP_FROM_EMAIL``); without SMTP config an in-memory mock provider
        records the send so the pipeline still advances (dry-run).

    The draft advances through ``send_status``: draft -> queued -> sent (or
    failed on a delivery error). ``status`` flips to ``sent`` only on success.
    """
    msg = outreach_crud.get(db, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if msg.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Only draft messages can be sent (current status: {msg.status})",
        )
    if msg.quality_gate_status != "ready":
        raise HTTPException(
            status_code=422,
            detail=(
                "quality gate must be 'ready' before sending "
                f"(current: {msg.quality_gate_status or 'unscored'})"
            ),
        )
    recipient = (msg.recipient_email or "").strip()
    if not recipient:
        raise HTTPException(
            status_code=422, detail="recipient_email is required to send this draft"
        )

    sender = get_email_sender()
    validation_error = sender.validate_recipient(recipient)
    if validation_error:
        raise HTTPException(status_code=422, detail=validation_error)

    # Advance through the pipeline and deliver.
    outreach_crud.set_send_status(db, msg, "queued")
    receipt = sender.send_email(
        subject=msg.subject,
        body=msg.body,
        recipient=recipient,
        sender=sender.from_email or None,
    )

    if receipt.success:
        outreach_crud.mark_sent(
            db,
            msg,
            sender=receipt.sender,
            recipient=recipient,
            sent_time=datetime.now(timezone.utc),
        )
        try:  # best-effort: send event for the CRM timeline
            events_crud.create(
                db, lead_id=msg.lead_id, event_type="sent", message_id=msg.id
            )
        except Exception:
            pass
        return SendDraftResponse(
            success=True, message_id=msg.id, sent_at=msg.sent_at, send_status="sent"
        )

    outreach_crud.set_send_status(db, msg, "failed")
    return SendDraftResponse(
        success=False,
        message_id=msg.id,
        send_status="failed",
        error=receipt.error,
    )
