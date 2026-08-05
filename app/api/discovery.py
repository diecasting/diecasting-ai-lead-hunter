"""Phase 5 Stage 1 — Lead Discovery API.

POST /discovery/analyze-url   — crawl a prospect URL, extract the industrial
                                profile, compute the lead score + recommended
                                contact role, and persist a CompanyDiscovery.
GET  /discovery               — list past discoveries (newest first).
POST /discovery/{id}/lead     — add a discovery to the CRM as a CompanyLead
                                (dedup by website). No email is sent here —
                                the existing Lead -> Outreach pipeline takes
                                over from the lead's detail page.
"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.database import get_db
from app.discovery import crud as discovery_crud
from app.discovery import queue as discovery_queue
from app.discovery import scheduler as discovery_scheduler
from app.discovery.analyzer import analyze_website
from app.models.company_discovery import CompanyDiscovery
from app.schemas.lead import CompanyLeadRead

router = APIRouter(prefix="/discovery", tags=["discovery"])


class AnalyzeUrlRequest(BaseModel):
    """Payload: the prospect's website URL to analyse."""

    url: str


class CreateJobRequest(BaseModel):
    """Payload: the search keyword driving a batch discovery job."""

    keyword: str


class JobTaskRead(BaseModel):
    """One analysed URL within a discovery job."""

    id: int
    url: str
    status: str  # pending | analyzed | failed | skipped
    discovery_id: Optional[int] = None
    error_message: Optional[str] = None
    company_name: Optional[str] = None
    lead_score: Optional[int] = None
    confidence_score: Optional[int] = None


class JobRead(BaseModel):
    """A discovery job with progress + per-task results."""

    id: int
    keyword: str
    status: str
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    tasks: List[JobTaskRead] = []


def _job_to_read(job) -> JobRead:
    progress = discovery_queue.job_progress(job)
    return JobRead(
        id=job.id,
        keyword=job.keyword,
        status=job.status,
        total=progress["total"],
        processed=progress["processed"],
        success=progress["success"],
        failed=progress["failed"],
        skipped=progress["skipped"],
        created_at=job.created_at.isoformat() if job.created_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        tasks=[
            JobTaskRead(
                id=t.id,
                url=t.url,
                status=t.status,
                discovery_id=t.discovery_id,
                error_message=t.error_message,
                company_name=(
                    t.discovery.company_name if t.discovery is not None else None
                ),
                lead_score=t.discovery.lead_score if t.discovery is not None else None,
                confidence_score=(
                    t.discovery.confidence_score if t.discovery is not None else None
                ),
            )
            for t in job.tasks
        ],
    )


class DiscoveryRead(BaseModel):
    """A persisted discovery record with the flattened analysis profile."""

    id: int
    company_name: str
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    business_type: Optional[str] = None
    description: Optional[str] = None
    products: List[str] = []
    industries_served: List[str] = []
    detected_materials: List[str] = []
    detected_processes: List[str] = []
    buying_signals: List[str] = []
    supplier_opportunities: List[str] = []
    discovery_source: str = "url_analysis"
    confidence_score: Optional[int] = None
    lead_score: Optional[int] = None
    recommended_contact_role: Optional[str] = None
    procurement_type: Optional[str] = None
    procurement_score: Optional[int] = None
    lead_id: Optional[int] = None
    created_at: Optional[str] = None


def _to_read(row: CompanyDiscovery) -> DiscoveryRead:
    """Map a CompanyDiscovery row (profile JSON) into the API response."""
    profile = {}
    if row.profile:
        try:
            profile = json.loads(row.profile)
        except Exception:
            profile = {}
    return DiscoveryRead(
        id=row.id,
        company_name=row.company_name,
        website=row.website,
        country=row.country,
        industry=row.industry,
        business_type=profile.get("business_type") or None,
        description=profile.get("description") or None,
        products=profile.get("products") or [],
        industries_served=profile.get("industries_served") or [],
        detected_materials=(row.detected_materials or "").split(", ") if row.detected_materials else [],
        detected_processes=(row.detected_processes or "").split(", ") if row.detected_processes else [],
        buying_signals=(row.buying_signals or "; ").split("; ") if row.buying_signals else [],
        supplier_opportunities=profile.get("supplier_opportunities") or [],
        discovery_source=row.discovery_source,
        confidence_score=row.confidence_score,
        lead_score=row.lead_score,
        recommended_contact_role=row.recommended_contact_role,
        procurement_type=profile.get("procurement_type") or None,
        procurement_score=profile.get("procurement_score") or None,
        lead_id=row.lead_id,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.post("/analyze-url", response_model=DiscoveryRead)
def analyze_url(payload: AnalyzeUrlRequest, db: Session = Depends(get_db)):
    """Crawl a prospect's website and produce a qualification-ready profile.

    Returns the company profile, the deterministic 0-100 lead score and the
    recommended primary contact role. The analysis is persisted as a
    ``CompanyDiscovery``; use ``POST /discovery/{id}/lead`` to add it to the
    CRM.
    """
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url is required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must start with http(s)://")

    try:
        result = analyze_website(url)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Website analysis failed: {exc}"
        )

    row = discovery_crud.create(
        db,
        company_name=result.company_name,
        website=result.url,
        country=result.country or None,
        industry=result.industry or None,
        detected_materials=", ".join(result.detected_materials) or None,
        detected_processes=", ".join(result.detected_processes) or None,
        buying_signals="; ".join(result.buying_signals) or None,
        discovery_source=result.discovery_source,
        confidence_score=result.confidence_score,
        lead_score=result.lead_score,
        recommended_contact_role=result.recommended_contact_role,
        profile=result.to_profile_json(),
    )
    return _to_read(row)


@router.get("", response_model=List[DiscoveryRead])
def list_discoveries(
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """Return recent discovery analyses, newest first."""
    rows = discovery_crud.list_all(db, limit=limit)
    return [_to_read(r) for r in rows]


@router.post("/{discovery_id}/lead", response_model=CompanyLeadRead, status_code=201)
def add_discovery_to_crm(discovery_id: int, db: Session = Depends(get_db)):
    """Add a discovery to the CRM as a lead (dedup by website).

    Only creates the ``CompanyLead`` row (``lead_source='discovery'``); no
    email is sent. The existing Lead -> Outreach pipeline (generate email,
    quality gate, send) applies from the lead's detail page. Uses the same
    qualification pipeline as the scheduler's auto-qualification.
    """
    from app.discovery.qualify import discovery_to_lead

    row = discovery_crud.get(db, discovery_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Discovery not found")

    lead, status = discovery_to_lead(db, row)
    if status == "created":
        return lead
    if status == "already_linked":
        raise HTTPException(
            status_code=409,
            detail=f"Discovery already added to CRM as lead #{lead.id}",
        )
    raise HTTPException(
        status_code=409,
        detail=f"Lead with website already exists (lead #{lead.id})",
    )


# ---------------------------------------------------------------------------
# Phase 5 Stage 2: Batch discovery jobs
# ---------------------------------------------------------------------------
@router.post("/jobs", response_model=dict, status_code=201)
def create_discovery_job(payload: CreateJobRequest, db: Session = Depends(get_db)):
    """Create a pending batch discovery job for a search keyword.

    Returns the ``job_id``; call ``POST /discovery/jobs/{id}/run`` to resolve
    candidate URLs from the keyword, analyse them, and track progress.
    """
    keyword = (payload.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword is required")
    job = discovery_queue.create_job(db, keyword)
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_discovery_job(job_id: int, db: Session = Depends(get_db)):
    """Return a discovery job with progress + per-task results.

    Progress: ``total`` / ``processed`` / ``success`` (analyzed) / ``failed`` /
    ``skipped`` (duplicates). Tasks carry the linked discovery's company name
    and lead score so the dashboard can bulk-add them to the CRM.
    """
    job = discovery_queue.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    return _job_to_read(job)


@router.post("/jobs/{job_id}/run", response_model=JobRead)
def run_discovery_job(job_id: int, db: Session = Depends(get_db)):
    """Execute a discovery job: resolve URLs, analyse each, track progress.

    Reuses the Stage 1 website analyzer (extraction + scoring) and duplicate
    detection (URLs already known to the CRM or prior discoveries are
    skipped). Existing outreach workflow is untouched.

    When the search provider is unavailable (e.g. ``SEARCH_PROVIDER=serpapi``
    without a key) the job fails with a clear ``error`` instead of silently
    returning zero URLs.
    """
    job = discovery_queue.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Discovery job is already running")
    result = discovery_queue.run_job(db, job)
    db.refresh(job)
    read = _job_to_read(job)
    if result.get("error"):
        read = read.model_copy(update={"error": result["error"]})
    return read


# ---------------------------------------------------------------------------
# Phase 5 Stage 3: Discovery schedules (recurring + auto-qualification)
# ---------------------------------------------------------------------------
class ScheduleCreate(BaseModel):
    """Payload for a recurring discovery schedule."""

    keyword: str
    frequency: str = "daily"  # daily | weekly | monthly
    enabled: bool = True
    lead_score_threshold: int = 50
    confidence_threshold: int = 40


class ScheduleUpdate(BaseModel):
    """Partial update for a discovery schedule."""

    keyword: Optional[str] = None
    frequency: Optional[str] = None
    enabled: Optional[bool] = None
    lead_score_threshold: Optional[int] = None
    confidence_threshold: Optional[int] = None


class ScheduleRead(BaseModel):
    """A recurring discovery schedule."""

    id: int
    keyword: str
    frequency: str
    enabled: bool
    lead_score_threshold: int
    confidence_threshold: int
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    created_at: Optional[str] = None


def _schedule_to_read(s) -> ScheduleRead:
    return ScheduleRead(
        id=s.id,
        keyword=s.keyword,
        frequency=s.frequency,
        enabled=s.enabled,
        lead_score_threshold=s.lead_score_threshold,
        confidence_threshold=s.confidence_threshold,
        last_run=s.last_run.isoformat() if s.last_run else None,
        next_run=s.next_run.isoformat() if s.next_run else None,
        created_at=s.created_at.isoformat() if s.created_at else None,
    )


def _validate_frequency(frequency: str) -> str:
    freq = (frequency or "daily").lower()
    if freq not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=422, detail="frequency must be one of: daily, weekly, monthly"
        )
    return freq


@router.post("/schedules", response_model=ScheduleRead, status_code=201)
def create_schedule(payload: ScheduleCreate, db: Session = Depends(get_db)):
    """Create a recurring discovery schedule (auto-runs on the daily hook)."""
    keyword = (payload.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword is required")
    schedule = discovery_scheduler.create_schedule(
        db,
        keyword=keyword,
        frequency=_validate_frequency(payload.frequency),
        enabled=payload.enabled,
        lead_score_threshold=payload.lead_score_threshold,
        confidence_threshold=payload.confidence_threshold,
    )
    return _schedule_to_read(schedule)


@router.get("/schedules", response_model=List[ScheduleRead])
def list_schedules(db: Session = Depends(get_db)):
    """Return all recurring discovery schedules."""
    return [_schedule_to_read(s) for s in discovery_scheduler.list_schedules(db)]


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: int, payload: ScheduleUpdate, db: Session = Depends(get_db)
):
    """Update a schedule (frequency / enabled / thresholds)."""
    schedule = discovery_scheduler.get_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Discovery schedule not found")
    fields = payload.model_dump(exclude_unset=True)
    if "frequency" in fields and fields["frequency"]:
        fields["frequency"] = _validate_frequency(fields["frequency"])
    if "keyword" in fields:
        fields["keyword"] = (fields["keyword"] or "").strip()
        if not fields["keyword"]:
            raise HTTPException(status_code=422, detail="keyword is required")
    updated = discovery_scheduler.update_schedule(db, schedule, **fields)
    return _schedule_to_read(updated)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Delete a recurring discovery schedule (history jobs are kept)."""
    schedule = discovery_scheduler.get_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Discovery schedule not found")
    discovery_scheduler.delete_schedule(db, schedule)


@router.get("/schedules/{schedule_id}/history", response_model=List[JobRead])
def schedule_history(schedule_id: int, db: Session = Depends(get_db)):
    """Execution history for a schedule: its discovery jobs, newest first."""
    schedule = discovery_scheduler.get_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Discovery schedule not found")
    return [_job_to_read(job) for job in schedule.jobs]


@router.post("/schedules/{schedule_id}/run", response_model=JobRead)
def run_schedule_now(schedule_id: int, db: Session = Depends(get_db)):
    """Run a schedule immediately (manual trigger); auto-qualifies results."""
    schedule = discovery_scheduler.get_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Discovery schedule not found")
    discovery_scheduler.run_schedule(db, schedule)
    db.refresh(schedule)
    job = schedule.jobs[0] if schedule.jobs else None
    if job is None:
        raise HTTPException(status_code=500, detail="Schedule run produced no job")
    return _job_to_read(job)
