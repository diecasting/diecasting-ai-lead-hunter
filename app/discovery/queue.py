"""Phase 5 Stage 2 — Batch Lead Discovery Queue.

A :class:`DiscoveryJob` batches keyword-driven prospect discovery:
``create_job`` records the keyword, ``run_job`` resolves candidate URLs from
the search keyword (reusing :class:`app.search.service.SearchService`),
deduplicates against the existing CRM + prior discoveries, then pushes each
URL through the Phase 5 Stage 1 website-analysis pipeline
(:func:`app.discovery.analyzer.analyze_website`), persisting one
``CompanyDiscovery`` per success. Progress is tracked on the job
(``total_urls`` / ``processed_urls`` / ``status``) and per task
(``pending`` / ``analyzed`` / ``failed`` / ``skipped``).

The search resolver and the crawler are injectable so tests run fully offline.
"""
from datetime import datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.discovery import crud as discovery_crud
from app.discovery.analyzer import analyze_website
from app.models.company_discovery import CompanyDiscovery
from app.models.discovery_job import DiscoveryJob, DiscoveryTask
from app.models.lead import CompanyLead

# Task statuses
TASK_PENDING = "pending"
TASK_ANALYZED = "analyzed"
TASK_FAILED = "failed"
TASK_SKIPPED = "skipped"

# Job statuses
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"

# Default maximum candidate URLs per job.
DEFAULT_MAX_URLS = 50


def create_job(db: Session, keyword: str) -> DiscoveryJob:
    """Create a pending discovery job for ``keyword``."""
    job = DiscoveryJob(keyword=(keyword or "").strip()[:255], status=JOB_PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[DiscoveryJob]:
    """Load a discovery job by id (or None)."""
    return db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()


def _resolve_urls(
    db: Session, keyword: str, *, resolver: Optional[Callable[[str], List[str]]] = None,
    max_urls: int = DEFAULT_MAX_URLS,
) -> List[str]:
    """Resolve candidate prospect URLs for a keyword (deduped, capped)."""
    if resolver is not None:
        urls = resolver(keyword)
    else:
        from app.search.service import SearchService

        urls = SearchService().search_urls(keyword, max_results=max_urls)
    seen: set = set()
    out: List[str] = []
    for u in urls or []:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max_urls:
            break
    return out


def _existing_websites(db: Session) -> set:
    """Lower-cased websites already known to the CRM or prior discoveries."""
    known = {
        row[0].lower()
        for row in db.query(CompanyLead.website)
        .filter(CompanyLead.website.isnot(None))
        .all()
    }
    known |= {
        row[0].lower()
        for row in db.query(CompanyDiscovery.website)
        .filter(CompanyDiscovery.website.isnot(None))
        .all()
    }
    return known


def job_progress(job: DiscoveryJob) -> dict:
    """Progress summary for a job: total / processed / success / failed / skipped."""
    counts = {"success": 0, "failed": 0, "skipped": 0}
    for task in job.tasks:
        if task.status == TASK_ANALYZED:
            counts["success"] += 1
        elif task.status == TASK_FAILED:
            counts["failed"] += 1
        elif task.status == TASK_SKIPPED:
            counts["skipped"] += 1
    return {
        "total": job.total_urls,
        "processed": job.processed_urls,
        "success": counts["success"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
    }


def run_job(
    db: Session,
    job: DiscoveryJob,
    *,
    resolver: Optional[Callable[[str], List[str]]] = None,
    crawler=None,
    max_urls: int = DEFAULT_MAX_URLS,
) -> dict:
    """Execute a discovery job: resolve URLs, analyse each, track progress.

    Reuses the Stage 1 website analyzer (extraction + scoring) and the
    duplicate detection (a URL already known to the CRM or to a prior
    discovery is skipped, not re-analysed). Individual failures are recorded
    per task; the job itself only fails on a fatal orchestration error.

    ``resolver`` (keyword -> urls) and ``crawler`` are injectable for tests.
    """
    job.status = JOB_RUNNING
    job.completed_at = None
    db.add(job)
    db.commit()

    try:
        urls = _resolve_urls(db, job.keyword, resolver=resolver, max_urls=max_urls)
        known = _existing_websites(db)

        # Create one task per URL, skipping URLs already known (DB) or
        # already present earlier in this batch.
        tasks: List[DiscoveryTask] = []
        seen_in_batch: set = set()
        for url in urls:
            task = DiscoveryTask(job_id=job.id, url=url, status=TASK_PENDING)
            db.add(task)
            db.flush()
            if url.lower() in known or url.lower() in seen_in_batch:
                task.status = TASK_SKIPPED
                task.error_message = "duplicate: website already known"
                known.add(url.lower())
                seen_in_batch.add(url.lower())
                job.processed_urls += 1
            else:
                seen_in_batch.add(url.lower())
                tasks.append(task)
        job.total_urls = len(urls)
        db.add(job)
        db.commit()

        # Analyse each new URL.
        for task in tasks:
            try:
                result = analyze_website(task.url, crawler=crawler)
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
                task.status = TASK_ANALYZED
                task.discovery_id = row.id
                task.error_message = None
            except Exception as exc:  # per-URL isolation
                task.status = TASK_FAILED
                task.error_message = str(exc)[:1000]
            finally:
                task.job.processed_urls += 1
                db.add(task)
                db.commit()

        job.status = JOB_COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        return job_progress(job)
    except Exception as exc:
        db.rollback()
        job.status = JOB_FAILED
        job.completed_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        return {
            "total": job.total_urls,
            "processed": job.processed_urls,
            "success": 0,
            "failed": job.processed_urls,
            "skipped": 0,
            "error": str(exc)[:1000],
        }
