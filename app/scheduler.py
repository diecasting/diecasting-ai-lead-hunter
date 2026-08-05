"""APScheduler-based daily lead-generation scheduler (Phase 2.5).

Runs ``run_full_pipeline`` every day at ``SCHEDULER_HOUR``:``SCHEDULER_MINUTE``
(local time). Disabled by default; enable via ``SCHEDULER_ENABLED=true``.

We deliberately use APScheduler (in-process) rather than Celery + Redis to keep
the deployment a single container — the daily job is lightweight and does not
need a separate worker broker.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import SessionLocal

scheduler = BackgroundScheduler(timezone="UTC")


def _job() -> None:
    """Open a DB session and run the full pipeline + outreach automation."""
    db = SessionLocal()
    try:
        # Imported lazily to avoid a circular import at module load time.
        from app.pipeline import run_full_pipeline

        report = run_full_pipeline(db)
        print(f"[scheduler] daily pipeline finished: {report}")

        # Phase 2.5: process HIGH-priority new leads through the outreach
        # workflow (generate email + schedule follow-ups). Dry-run by default;
        # set SMTP_* in the environment and pass dry_run=False to actually send.
        from app.outreach.workflow import run_daily_pipeline

        outreach_report = run_daily_pipeline(db, dry_run=True)
        print(f"[scheduler] outreach automation finished: {outreach_report}")

        # Phase 5 Stage 3: run due recurring discovery schedules; qualified
        # discoveries are auto-added to the CRM (no emails here).
        from app.discovery.scheduler import run_due_schedules

        discovery_report = run_due_schedules(db)
        print(f"[scheduler] discovery automation finished: {discovery_report}")
    except Exception as exc:  # pragma: no cover - depends on live services
        print(f"[scheduler] pipeline error: {exc}")
    finally:
        db.close()


def start_scheduler() -> None:
    if not settings.scheduler_enabled:
        print("[scheduler] disabled (SCHEDULER_ENABLED is false).")
        return
    if scheduler.get_job("daily_lead_gen") is None:
        scheduler.add_job(
            _job,
            trigger=CronTrigger(
                hour=settings.scheduler_hour, minute=settings.scheduler_minute
            ),
            id="daily_lead_gen",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if not scheduler.running:
        scheduler.start()
    print(
        f"[scheduler] started — daily lead generation at "
        f"{settings.scheduler_hour:02d}:{settings.scheduler_minute:02d} UTC."
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
