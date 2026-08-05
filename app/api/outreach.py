"""Outreach API routes — email generation and draft management."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
    updated = outreach_crud.set_gate_status(db, msg, payload.gate_status)
    # Phase 4.6: releasing a draft to 'ready' is the approval event on the
    # lead's outreach timeline.
    if payload.gate_status == "ready":
        try:
            events_crud.create(
                db, lead_id=msg.lead_id, event_type="approved", message_id=msg.id
            )
        except Exception:
            pass  # timeline recording is best-effort
    return updated


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
        # Phase 4.6: a delivered email advances the lead pipeline to 'sent'.
        try:
            from app.outreach.workflow import transition as transition_status

            lead = leads_crud.get(db, msg.lead_id)
            if lead is not None and lead.lead_status in ("new", "qualified"):
                transition_status(lead, "sent", db=db)
        except Exception:
            pass
        # Phase 6 Stage 1: automatically schedule follow-ups for unanswered
        # outreach (created from the lead's default sequence; idempotent).
        try:
            from app.outreach.followup.scheduler import schedule_for_lead

            lead = leads_crud.get(db, msg.lead_id)
            if lead is not None:
                schedule_for_lead(db, lead, msg)
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


# ---------------------------------------------------------------------------
# Phase 6 Stage 1: AI Follow-up Automation
# ---------------------------------------------------------------------------
class SequenceCreate(BaseModel):
    """Payload for creating a follow-up sequence."""

    name: str
    steps: List[dict]
    enabled: bool = True


class SequenceUpdate(BaseModel):
    """Partial update for a follow-up sequence (pause/resume)."""

    name: Optional[str] = None
    steps: Optional[List[dict]] = None
    enabled: Optional[bool] = None


class SequenceRead(BaseModel):
    """A follow-up sequence with its steps."""

    id: int
    name: str
    steps: List[dict] = []
    enabled: bool = True
    created_at: Optional[datetime] = None


class StartFollowupRequest(BaseModel):
    """Start the follow-up schedule for a lead (optional sequence override)."""

    sequence_id: Optional[int] = None
    original_message_id: Optional[int] = None


class FollowUpRead(BaseModel):
    """One scheduled follow-up."""

    id: int
    lead_id: int
    lead_name: Optional[str] = None
    original_message_id: Optional[int] = None
    sequence_id: Optional[int] = None
    step_number: int
    scheduled_at: Optional[datetime] = None
    status: str = "pending"
    message_id: Optional[int] = None
    created_at: Optional[datetime] = None


class FollowUpStatusUpdate(BaseModel):
    """Pause / resume a scheduled follow-up."""

    status: str  # pending | cancelled


def _sequence_to_read(s) -> SequenceRead:
    return SequenceRead(
        id=s.id,
        name=s.name,
        steps=s.steps_list(),
        enabled=s.enabled,
        created_at=s.created_at,
    )


def _followup_to_read(fu) -> FollowUpRead:
    return FollowUpRead(
        id=fu.id,
        lead_id=fu.lead_id,
        lead_name=fu.lead.name if fu.lead is not None else None,
        original_message_id=fu.original_message_id,
        sequence_id=fu.sequence_id,
        step_number=fu.step_number,
        scheduled_at=fu.scheduled_at,
        status=fu.status,
        message_id=fu.message_id,
        created_at=fu.created_at,
    )


@router.post("/sequences", response_model=SequenceRead, status_code=201)
def create_sequence(payload: SequenceCreate, db: Session = Depends(get_db)):
    """Create a follow-up sequence (steps: [{delay_days, template}, ...])."""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    from app.outreach.followup import sequence as sequence_module

    try:
        seq = sequence_module.create_sequence(
            db, name=name, steps=payload.steps, enabled=payload.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _sequence_to_read(seq)


@router.get("/sequences", response_model=List[SequenceRead])
def list_sequences(db: Session = Depends(get_db)):
    """Return all follow-up sequences."""
    from app.outreach.followup import sequence as sequence_module

    return [_sequence_to_read(s) for s in sequence_module.list_sequences(db)]


@router.patch("/sequences/{sequence_id}", response_model=SequenceRead)
def update_sequence(
    sequence_id: int, payload: SequenceUpdate, db: Session = Depends(get_db)
):
    """Update a sequence (rename / steps / enable-disable for pause/resume)."""
    from app.outreach.followup import sequence as sequence_module

    seq = sequence_module.get_sequence(db, sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    fields = payload.model_dump(exclude_unset=True)
    try:
        updated = sequence_module.update_sequence(db, seq, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _sequence_to_read(updated)


@router.post("/leads/{lead_id}/start-followup", response_model=List[FollowUpRead])
def start_followup(
    lead_id: int,
    payload: StartFollowupRequest = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Start (or resume) the follow-up schedule for a lead.

    The schedule is built from the lead's default enabled sequence (or the
    explicit ``sequence_id``) against the lead's most recent sent message.
    Idempotent: existing pending/generated follow-ups are not duplicated.
    """
    from app.outreach.followup import scheduler as followup_scheduler

    lead = leads_crud.get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    original_message = None
    if payload is not None and payload.original_message_id is not None:
        original_message = outreach_crud.get(db, payload.original_message_id)
        if original_message is None:
            raise HTTPException(status_code=404, detail="Original message not found")
    else:
        sent = outreach_crud.get_by_lead(db, lead_id, status="sent")
        original_message = sent[0] if sent else None

    sequence_id = payload.sequence_id if payload is not None else None
    rows = followup_scheduler.schedule_for_lead(
        db, lead, original_message, sequence_id=sequence_id
    )
    return [_followup_to_read(fu) for fu in rows]


@router.get("/followups", response_model=List[FollowUpRead])
def list_followups(
    db: Session = Depends(get_db),
    status: str = Query(None, description="Filter: pending|generated|sent|cancelled"),
    lead_id: int = Query(None, description="Filter by lead"),
):
    """Return scheduled follow-ups, optionally filtered by status / lead."""
    from app.outreach.followup import scheduler as followup_scheduler

    rows = followup_scheduler.list_followups(db, status=status, lead_id=lead_id)
    return [_followup_to_read(fu) for fu in rows]


@router.patch("/followups/{followup_id}", response_model=FollowUpRead)
def update_followup_status(
    followup_id: int, payload: FollowUpStatusUpdate, db: Session = Depends(get_db)
):
    """Pause (cancelled) or resume (pending) a scheduled follow-up."""
    from app.outreach.followup import scheduler as followup_scheduler

    fu = followup_scheduler.get_followup(db, followup_id)
    if fu is None:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if payload.status not in ("pending", "cancelled"):
        raise HTTPException(
            status_code=422, detail="status must be one of: pending, cancelled"
        )
    return _followup_to_read(followup_scheduler.set_status(db, fu, payload.status))


@router.post("/followups/process", response_model=dict)
def process_due_followups_now(db: Session = Depends(get_db)):
    """Run the follow-up automation now: generate + send all due follow-ups.

    Guards the lead status (replied / rfq / customer / closed cancel the
    remaining follow-ups) and sends through the configured email provider.
    """
    from app.outreach.followup import scheduler as followup_scheduler

    return followup_scheduler.process_due_followups(db)
