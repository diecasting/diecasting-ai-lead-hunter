"""Phase 5 Stage 3 — Lead Discovery Scheduler and Qualification.

A :class:`DiscoverySchedule` repeats a keyword-driven discovery job on a
frequency. Each run creates a linked :class:`DiscoveryJob` (execution
history) and auto-qualifies discoveries:

Qualification rules (all must pass):
  * ``lead_score``        >= ``lead_score_threshold`` (default 50)
  * ``confidence_score``  >= ``confidence_threshold``  (default 40)
  * a manufacturing process was detected
  * a buying signal exists

Qualified discoveries are automatically added to the CRM as leads
(``lead_source='discovery'``, deduplicated by website / prior link).

The APScheduler daily job calls :func:`run_due_schedules` so enabled,
due schedules execute unattended.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.discovery import queue as discovery_queue
from app.discovery.qualify import discovery_to_lead, qualification_rules_pass
from app.models.discovery_job import DiscoveryJob
from app.models.discovery_schedule import DiscoverySchedule

FREQUENCIES = ("daily", "weekly", "monthly")

_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def compute_next_run(last_run: datetime, frequency: str) -> datetime:
    """Next scheduled run after ``last_run`` for the given frequency."""
    days = _DAYS.get((frequency or "daily").lower(), 1)
    return last_run + timedelta(days=days)


def create_schedule(
    db: Session,
    *,
    keyword: str,
    frequency: str = "daily",
    enabled: bool = True,
    lead_score_threshold: int = 50,
    confidence_threshold: int = 40,
) -> DiscoverySchedule:
    """Create a recurring discovery schedule (due immediately when enabled)."""
    schedule = DiscoverySchedule(
        keyword=(keyword or "").strip()[:255],
        frequency=(frequency or "daily").lower(),
        enabled=enabled,
        lead_score_threshold=lead_score_threshold,
        confidence_threshold=confidence_threshold,
        next_run=datetime.now(timezone.utc) if enabled else None,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def get_schedule(db: Session, schedule_id: int) -> Optional[DiscoverySchedule]:
    return (
        db.query(DiscoverySchedule)
        .filter(DiscoverySchedule.id == schedule_id)
        .first()
    )


def list_schedules(db: Session) -> List[DiscoverySchedule]:
    return db.query(DiscoverySchedule).order_by(DiscoverySchedule.id.desc()).all()


def update_schedule(
    db: Session, schedule: DiscoverySchedule, **fields
) -> DiscoverySchedule:
    """Update a schedule; re-enabling resets ``next_run`` to now."""
    for field, value in fields.items():
        if value is not None:
            setattr(schedule, field, value)
    if fields.get("enabled") is True and schedule.next_run is None:
        schedule.next_run = datetime.now(timezone.utc)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def delete_schedule(db: Session, schedule: DiscoverySchedule) -> None:
    db.delete(schedule)
    db.commit()


def run_schedule(
    db: Session,
    schedule: DiscoverySchedule,
    *,
    resolver=None,
    crawler=None,
    max_urls: int = 50,
) -> dict:
    """Execute one scheduled run: discover, qualify, auto-add to CRM.

    Creates a linked :class:`DiscoveryJob` (execution history), runs the batch
    queue, applies the qualification rules, and adds qualified discoveries to
    the CRM (duplicates / already-linked are reported, not re-created).
    """
    job = DiscoveryJob(keyword=schedule.keyword, schedule_id=schedule.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    progress = discovery_queue.run_job(
        db, job, resolver=resolver, crawler=crawler, max_urls=max_urls
    )

    # Auto-qualify analysed discoveries.
    db.refresh(job)
    qualified: List[int] = []
    added: List[int] = []
    not_qualified: List[dict] = []
    for task in job.tasks:
        if task.status != "analyzed" or task.discovery is None:
            continue
        disc = task.discovery
        ok, reason = qualification_rules_pass(
            disc,
            lead_score_threshold=schedule.lead_score_threshold,
            confidence_threshold=schedule.confidence_threshold,
        )
        if not ok:
            not_qualified.append(
                {"discovery_id": disc.id, "url": task.url, "reason": reason}
            )
            continue
        lead, status = discovery_to_lead(db, disc)
        qualified.append(disc.id)
        if status == "created":
            added.append(lead.id)
        else:
            not_qualified.append(
                {"discovery_id": disc.id, "url": task.url, "reason": status}
            )

    now = datetime.now(timezone.utc)
    schedule.last_run = now
    schedule.next_run = compute_next_run(now, schedule.frequency)
    db.add(schedule)
    db.commit()

    return {
        "schedule_id": schedule.id,
        "job_id": job.id,
        "progress": progress,
        "qualified": qualified,
        "added": added,
        "not_qualified": not_qualified,
    }


def run_due_schedules(
    db: Session, *, resolver=None, crawler=None, now: Optional[datetime] = None
) -> dict:
    """Run every enabled schedule that is due (never run, or next_run passed).

    This is the hook called by the APScheduler daily job.
    """
    now = now or datetime.now(timezone.utc)
    due = (
        db.query(DiscoverySchedule)
        .filter(
            DiscoverySchedule.enabled.is_(True),
            or_(DiscoverySchedule.next_run.is_(None), DiscoverySchedule.next_run <= now),
        )
        .order_by(DiscoverySchedule.id)
        .all()
    )
    runs = [run_schedule(db, s, resolver=resolver, crawler=crawler) for s in due]
    return {"schedules_due": len(due), "runs": runs}
