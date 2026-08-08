"""Reply Intelligence Sales Automation API (Phase 10).

Router prefix ``/api/reply``. This router *extends* the Phase 6 Reply
Intelligence engine — it reuses the existing inbox matcher, the
``reply_ai`` classifier / analyzer / action engine, and the CRM / Campaign
infrastructure. It never sends email or bypasses the outreach workflow.

Endpoints
---------
  GET  /api/reply/replies            list inbound replies (IncomingEmail)
  POST /api/reply/analyze            analyze an inbox reply (match -> classify -> act)
  GET  /api/reply/rfq-queue          RFQ extractions awaiting quotation
  GET  /api/reply/sales-tasks        list sales tasks
  POST /api/reply/sales-tasks        create a sales task
  GET  /api/reply/sales-tasks/{id}   get a sales task
  PUT  /api/reply/sales-tasks/{id}   update a sales task
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.incoming_email import IncomingEmail
from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis
from app.models.reply_rfq_extraction import ReplyRFQExtraction
from app.models.sales_task import (
    SalesTask,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TASK_STATUS_OPEN,
)
from app.outreach.inbox.matcher import match_incoming_email
from app.outreach.reply_ai import action as reply_action
from app.outreach.reply_ai import analyzer as reply_analyzer

router = APIRouter(prefix="/api/reply", tags=["reply-intelligence"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class IncomingReplyRead(BaseModel):
    id: int
    sender_email: str
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    received_at: Optional[datetime] = None
    processed: bool = False
    matched_lead_id: Optional[int] = None
    analysis_id: Optional[int] = None


class AnalyzeReplyRequest(BaseModel):
    """Analyze a reply either from a stored IncomingEmail or raw fields."""

    incoming_email_id: Optional[int] = None
    sender_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = Field(None, description="Reply body (required without incoming_email_id)")
    message_id: Optional[int] = None


class AnalyzeReplyResult(BaseModel):
    analysis_id: int
    lead_id: int
    intent: str
    confidence_score: Optional[float] = None
    recommended_action: Optional[str] = None
    applied_actions: List[str] = []
    sales_task_ids: List[int] = []
    rfq_extraction_id: Optional[int] = None


class RFQQueueItem(BaseModel):
    extraction_id: int
    analysis_id: int
    lead_id: int
    company_name: Optional[str] = None
    intent: str
    product: Optional[str] = None
    quantity: Optional[str] = None
    material: Optional[str] = None
    process: Optional[str] = None
    deadline: Optional[str] = None
    requirements: Optional[str] = None
    used_ai: bool = False
    created_at: Optional[datetime] = None


class SalesTaskRead(BaseModel):
    id: int
    reply_id: Optional[int] = None
    contact_id: Optional[int] = None
    company_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    priority: str
    status: str
    category: Optional[str] = None
    due_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SalesTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    category: Optional[str] = None
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    reply_id: Optional[int] = None
    due_at: Optional[datetime] = None


class SalesTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    due_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _serialize_task(t: SalesTask) -> Dict:
    return {
        "id": t.id,
        "reply_id": t.reply_id,
        "contact_id": t.contact_id,
        "company_id": t.company_id,
        "title": t.title,
        "description": t.description,
        "priority": t.priority,
        "status": t.status,
        "category": t.category,
        "due_at": t.due_at,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _incoming_to_read(row: IncomingEmail) -> IncomingReplyRead:
    return IncomingReplyRead(
        id=row.id,
        sender_email=row.sender_email,
        sender_name=row.sender_name,
        subject=row.subject,
        body=row.body,
        received_at=row.received_at,
        processed=row.processed,
        matched_lead_id=row.matched_lead_id,
        analysis_id=row.analysis_id,
    )


# ---------------------------------------------------------------------------
# Replies (inbox listing)
# ---------------------------------------------------------------------------
@router.get("/replies", response_model=List[IncomingReplyRead])
def list_replies(
    processed: Optional[str] = None,
    analyzed: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List inbound replies.

    Query params:
      * ``processed=true|false`` — filter on processing state.
      * ``analyzed=true|false``  — filter on whether an analysis is attached.
    """
    q = db.query(IncomingEmail)
    if processed == "true":
        q = q.filter(IncomingEmail.processed.is_(True))
    elif processed == "false":
        q = q.filter(IncomingEmail.processed.is_(False))
    if analyzed == "true":
        q = q.filter(IncomingEmail.analysis_id.isnot(None))
    elif analyzed == "false":
        q = q.filter(IncomingEmail.analysis_id.is_(None))
    rows = q.order_by(
        IncomingEmail.received_at.desc(), IncomingEmail.id.desc()
    ).all()
    return [_incoming_to_read(r) for r in rows]


# ---------------------------------------------------------------------------
# Analyze a reply (inbox-based)
# ---------------------------------------------------------------------------
@router.post("/analyze", response_model=AnalyzeReplyResult)
def analyze_reply(payload: AnalyzeReplyRequest, db: Session = Depends(get_db)):
    """Classify an inbound reply, apply the CRM + sales automation, and report.

    Accepts either a stored ``incoming_email_id`` or raw ``sender_email`` /
    ``subject`` / ``body`` fields. The reply is matched to a lead via the
    existing inbox matcher; if no lead matches a 404 is returned. The matched
    lead's reply is then run through the Phase 6 classifier / analyzer / action
    engine (extended in Phase 10 with sales tasks, RFQ extraction and campaign
    sync).
    """
    if not settings.reply_intelligence_enabled:
        raise HTTPException(status_code=503, detail="Reply intelligence is disabled")

    email: Optional[IncomingEmail] = None
    if payload.incoming_email_id is not None:
        email = (
            db.query(IncomingEmail)
            .filter(IncomingEmail.id == payload.incoming_email_id)
            .first()
        )
        if email is None:
            raise HTTPException(status_code=404, detail="Incoming email not found")
    else:
        if not payload.body:
            raise HTTPException(
                status_code=422, detail="body is required when incoming_email_id is omitted"
            )
        email = IncomingEmail(
            sender_email=payload.sender_email or "",
            sender_name=None,
            subject=payload.subject or "",
            body=payload.body,
            received_at=datetime.now(timezone.utc),
        )

    match = match_incoming_email(db, email)
    if match is None:
        raise HTTPException(status_code=404, detail="No matching lead for this reply")

    lead, message = match
    analysis, actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text=email.body or "",
        message_id=message.id if message else payload.message_id,
    )

    task_ids = [t.id for t in analysis.sales_tasks]
    rfq = analysis.rfq_extraction
    rfq_id = rfq.id if rfq else None

    # Persist the linkage back onto the stored inbox row (best-effort).
    if payload.incoming_email_id is not None:
        email.processed = True
        email.matched_lead_id = lead.id
        email.analysis_id = analysis.id
        db.add(email)
        db.commit()

    return AnalyzeReplyResult(
        analysis_id=analysis.id,
        lead_id=lead.id,
        intent=analysis.intent,
        confidence_score=analysis.confidence_score,
        recommended_action=analysis.recommended_action,
        applied_actions=actions,
        sales_task_ids=task_ids,
        rfq_extraction_id=rfq_id,
    )


# ---------------------------------------------------------------------------
# RFQ queue
# ---------------------------------------------------------------------------
@router.get("/rfq-queue", response_model=List[RFQQueueItem])
def rfq_queue(db: Session = Depends(get_db)):
    """List RFQ extractions (one per ``rfq_request`` reply) for the sales team."""
    rows = (
        db.query(ReplyRFQExtraction)
        .join(ReplyAnalysis, ReplyAnalysis.id == ReplyRFQExtraction.analysis_id)
        .order_by(ReplyRFQExtraction.id.desc())
        .all()
    )
    out: List[RFQQueueItem] = []
    for ext in rows:
        a = ext.analysis
        lead = None
        if a is not None:
            lead = db.query(CompanyLead).filter(CompanyLead.id == a.lead_id).first()
        out.append(
            RFQQueueItem(
                extraction_id=ext.id,
                analysis_id=ext.analysis_id,
                lead_id=a.lead_id if a else None,
                company_name=lead.name if lead else None,
                intent=a.intent if a else None,
                product=ext.product,
                quantity=ext.quantity,
                material=ext.material,
                process=ext.process,
                deadline=ext.deadline,
                requirements=ext.requirements,
                used_ai=ext.used_ai,
                created_at=ext.created_at,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Sales tasks CRUD
# ---------------------------------------------------------------------------
@router.get("/sales-tasks", response_model=List[SalesTaskRead])
def list_sales_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(SalesTask)
    if status:
        q = q.filter(SalesTask.status == status)
    if priority:
        q = q.filter(SalesTask.priority == priority)
    if category:
        q = q.filter(SalesTask.category == category)
    rows = q.order_by(SalesTask.id.desc()).all()
    return [_serialize_task(t) for t in rows]


@router.post("/sales-tasks", response_model=SalesTaskRead)
def create_sales_task(payload: SalesTaskCreate, db: Session = Depends(get_db)):
    if payload.priority not in TASK_PRIORITIES:
        raise HTTPException(
            status_code=422, detail=f"priority must be one of: {', '.join(TASK_PRIORITIES)}"
        )
    task = SalesTask(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status=TASK_STATUS_OPEN,
        category=payload.category,
        company_id=payload.company_id,
        contact_id=payload.contact_id,
        reply_id=payload.reply_id,
        due_at=payload.due_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.get("/sales-tasks/{task_id}", response_model=SalesTaskRead)
def get_sales_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(SalesTask).filter(SalesTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Sales task not found")
    return _serialize_task(task)


@router.put("/sales-tasks/{task_id}", response_model=SalesTaskRead)
def update_sales_task(
    task_id: int, payload: SalesTaskUpdate, db: Session = Depends(get_db)
):
    task = db.query(SalesTask).filter(SalesTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Sales task not found")
    fields = payload.model_dump(exclude_none=True)
    if "priority" in fields and fields["priority"] not in TASK_PRIORITIES:
        raise HTTPException(
            status_code=422, detail=f"priority must be one of: {', '.join(TASK_PRIORITIES)}"
        )
    if "status" in fields and fields["status"] not in TASK_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"status must be one of: {', '.join(TASK_STATUSES)}"
        )
    for key, value in fields.items():
        setattr(task, key, value)
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)
