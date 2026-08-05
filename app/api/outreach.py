"""Outreach API routes — email generation and draft management."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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


# ---------------------------------------------------------------------------
# Phase 6 Stage 2: AI Reply Intelligence
# ---------------------------------------------------------------------------
class ReplyAnalyzeRequest(BaseModel):
    """Payload for classifying an inbound customer reply."""

    lead_id: int
    message_id: Optional[int] = None
    reply_text: str = Field(..., min_length=1, description="The customer's reply body")


class ReplyAnalysisRead(BaseModel):
    """A classified reply with the CRM actions that were applied."""

    id: int
    lead_id: int
    message_id: Optional[int] = None
    reply_text: str
    intent: str
    confidence_score: Optional[float] = None
    recommended_action: Optional[str] = None
    applied_actions: List[str] = []
    created_at: Optional[datetime] = None


def _reply_analysis_to_read(a, actions: Optional[List[str]] = None) -> ReplyAnalysisRead:
    return ReplyAnalysisRead(
        id=a.id,
        lead_id=a.lead_id,
        message_id=a.message_id,
        reply_text=a.reply_text,
        intent=a.intent,
        confidence_score=a.confidence_score,
        recommended_action=a.recommended_action,
        applied_actions=actions or [],
        created_at=a.created_at,
    )


@router.post("/replies/analyze", response_model=ReplyAnalysisRead)
def analyze_reply(
    payload: ReplyAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """Classify a customer reply and apply the intent-driven CRM automation.

    Intent rules (Phase 6 Stage 2):
      * ``rfq_request``     → lead status → ``rfq``
      * ``interested``      → lead status → ``qualified``
      * ``not_interested``  → stop follow-ups + mark do-not-contact
      * ``supplier_existing``→ stop the follow-up sequence

    Returns the analysis (intent / confidence / recommended_action) plus the
    list of CRM actions that were applied.
    """
    from app.outreach import reply_ai

    lead = leads_crud.get(db, payload.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.message_id is not None:
        msg = outreach_crud.get(db, payload.message_id)
        if msg is None or msg.lead_id != lead.id:
            raise HTTPException(
                status_code=404, detail="Message not found for this lead"
            )

    analysis, actions = reply_ai.analyze_reply(
        db,
        lead,
        reply_text=payload.reply_text,
        message_id=payload.message_id,
    )
    return _reply_analysis_to_read(analysis, actions)


@router.get("/leads/{lead_id}/reply-analysis", response_model=List[ReplyAnalysisRead])
def list_reply_analyses(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Return all reply analyses for a lead, newest first."""
    from app.outreach import reply_ai

    lead = leads_crud.get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    rows = reply_ai.list_analyses(db, lead_id)
    return [_reply_analysis_to_read(a) for a in rows]


# ---------------------------------------------------------------------------
# Phase 6 Stage 3: Reply Inbox Connector
# ---------------------------------------------------------------------------
class IncomingEmailRead(BaseModel):
    """An inbound inbox email with its analysis outcome."""

    id: int
    sender_email: str
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    received_at: Optional[datetime] = None
    processed: bool = False
    matched_lead_id: Optional[int] = None
    matched_lead_name: Optional[str] = None
    message_id: Optional[int] = None
    analysis_id: Optional[int] = None
    intent: Optional[str] = None
    confidence_score: Optional[float] = None
    recommended_action: Optional[str] = None


def _incoming_to_read(row) -> IncomingEmailRead:
    analysis = row.analysis if row.analysis_id is not None else None
    return IncomingEmailRead(
        id=row.id,
        sender_email=row.sender_email,
        sender_name=row.sender_name,
        subject=row.subject,
        body=row.body,
        received_at=row.received_at,
        processed=row.processed,
        matched_lead_id=row.matched_lead_id,
        matched_lead_name=row.lead.name if row.lead is not None else None,
        message_id=row.message_id,
        analysis_id=row.analysis_id,
        intent=analysis.intent if analysis is not None else None,
        confidence_score=analysis.confidence_score if analysis is not None else None,
        recommended_action=(
            analysis.recommended_action if analysis is not None else None
        ),
    )


@router.get("/inbox", response_model=List[IncomingEmailRead])
def list_inbox(
    db: Session = Depends(get_db),
    processed: Optional[str] = Query(
        None,
        pattern="^(true|false)$",
        description="Filter by processed state: true | false",
    ),
):
    """Return inbox emails (newest first), optionally filtered by state."""
    from app.models.incoming_email import IncomingEmail

    q = db.query(IncomingEmail)
    if processed is not None:
        q = q.filter(IncomingEmail.processed.is_(processed == "true"))
    rows = (
        q.order_by(IncomingEmail.received_at.desc(), IncomingEmail.id.desc())
        .limit(200)
        .all()
    )
    return [_incoming_to_read(r) for r in rows]


@router.post("/inbox/process", response_model=dict)
def process_inbox_now(db: Session = Depends(get_db)):
    """Fetch new replies from the inbox and feed them into the Reply
    Intelligence Engine (match lead → classify → apply CRM actions).

    Returns a summary: fetched / new_emails / duplicates / processed /
    matched / unmatched / analyzed. Unmatched emails stay unprocessed so they
    remain visible in GET /outreach/inbox/unprocessed for manual review.
    """
    from app.outreach.inbox.processor import process_inbox

    return process_inbox(db)


@router.get("/inbox/unprocessed", response_model=List[IncomingEmailRead])
def list_unprocessed_inbox(db: Session = Depends(get_db)):
    """Return inbox emails that have not been processed yet (incl. unmatched)."""
    from app.models.incoming_email import IncomingEmail

    rows = (
        db.query(IncomingEmail)
        .filter(IncomingEmail.processed.is_(False))
        .order_by(IncomingEmail.received_at.desc(), IncomingEmail.id.desc())
        .all()
    )
    return [_incoming_to_read(r) for r in rows]


@router.get("/inbox/status", response_model=dict)
def inbox_status(db: Session = Depends(get_db)):
    """Return the inbox connector configuration + derived stats.

    Never exposes IMAP_PASSWORD. ``configured`` is true only when host +
    credentials (including password) are set. ``fetched_count`` is the number
    of emails pulled into the reply inbox so far; ``last_check_at`` is the
    most recent email fetch time (newest incoming row).
    """
    from app.config import settings
    from app.models.incoming_email import IncomingEmail
    from app.outreach.inbox.connector import imap_configured

    configured = imap_configured()
    last = (
        db.query(IncomingEmail)
        .order_by(IncomingEmail.created_at.desc(), IncomingEmail.id.desc())
        .first()
    )
    return {
        "provider": "imap" if configured else "mock",
        "configured": configured,
        "server": settings.imap_host or "",
        "username": settings.imap_username or "",
        "folder": settings.imap_folder or "INBOX",
        "use_ssl": settings.imap_use_ssl,
        "fetched_count": db.query(IncomingEmail).count(),
        "last_check_at": last.created_at if last is not None else None,
    }


@router.post("/inbox/test", response_model=dict)
def inbox_test():
    """Test the IMAP connection: connect + authenticate + read INBOX.

    Returns the connection result, the INBOX message count, and a preview of
    the latest 5 emails (sender / subject). Read-only — does NOT modify the
    reply analysis workflow (no DB writes, no \\Seen flags). Without IMAP
    configuration the mock provider is used (dry-run success).
    """
    from app.outreach.inbox.connector import get_inbox_connector, imap_configured

    result = get_inbox_connector().test_connection()
    result["configured"] = imap_configured()
    return result


# ---------------------------------------------------------------------------
# Phase 6 Stage 4: SMTP provider status + connectivity test
# ---------------------------------------------------------------------------
class EmailTestRequest(BaseModel):
    """Optional payload for the SMTP connectivity test."""

    recipient: Optional[str] = None
    subject: str = "Lead Hunter SMTP test"
    body: str = "This is a test email from the Lead Hunter sending pipeline."


@router.get("/email-status", response_model=dict)
def email_status():
    """Return the active email provider configuration.

    Never exposes the password. ``configured`` is true only when host +
    credentials (including password) are set; otherwise the mock provider
    (dry-run) is active.
    """
    from app.config import settings
    from app.outreach.sender import _smtp_configured, smtp_implicit_ssl

    configured = _smtp_configured()
    return {
        "provider": "smtp" if configured else "mock",
        "configured": configured,
        "sender_email": (
            settings.smtp_from_email or settings.smtp_username or settings.smtp_user or ""
        ),
        "smtp_host": settings.smtp_host or "",
        "smtp_port": settings.smtp_port,
        "use_ssl": smtp_implicit_ssl(),
    }


@router.post("/email-test", response_model=dict)
def email_test(payload: Optional[EmailTestRequest] = None):
    """Send a real test email through the configured SMTP provider.

    Verifies connectivity + authentication. Does NOT modify the outreach
    workflow — no outreach messages or events are written. Without SMTP
    configuration the mock provider is used (dry-run success), so the
    endpoint is fully testable offline.
    """
    from app.config import settings
    from app.outreach.sender import _smtp_configured, get_email_sender

    sender = get_email_sender()
    recipient = (payload.recipient or "").strip() if payload is not None else ""
    if not recipient:
        recipient = (
            settings.smtp_from_email
            or settings.smtp_username
            or settings.smtp_user
            or ""
        ).strip()
    validation_error = sender.validate_recipient(recipient)
    if validation_error:
        raise HTTPException(status_code=422, detail=validation_error)

    subject = payload.subject if payload is not None else "Lead Hunter SMTP test"
    body = (
        payload.body
        if payload is not None
        else "This is a test email from the Lead Hunter sending pipeline."
    )
    receipt = sender.send_email(
        subject=subject,
        body=body,
        recipient=recipient,
        sender=sender.from_email or None,
    )
    return {
        "success": receipt.success,
        "provider": "smtp" if _smtp_configured() else "mock",
        "configured": _smtp_configured(),
        "dry_run": receipt.dry_run,
        "recipient": recipient,
        "sent_at": receipt.sent_at,
        "error": receipt.error,
    }
