"""Crawl runner: turns pending ``crawl_tasks`` into crawled leads.

Shared by the REST endpoint (``POST /crawl/run``) and the scheduled pipeline so
the crawling logic lives in exactly one place. Responsible for flipping task
status (running → success/failed with retry), extracting e-mails, and updating
the parent ``CompanyLead``.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.crawler.website_crawler import WebsiteCrawler
from app.crud import crawl_tasks as crawl_tasks_crud
from app.crud import leads as leads_crud


def process_task(db: Session, task, crawler: Optional[WebsiteCrawler] = None) -> dict:
    """Crawl a single task and persist the outcome. Returns a status dict."""
    crawler = crawler or WebsiteCrawler()
    crawl_tasks_crud.mark_running(db, task)
    db.commit()

    try:
        outcome = crawler.crawl(task.url or "")
    except Exception as exc:  # crawler raised before producing an outcome
        crawl_tasks_crud.mark_failed(db, task=task, error=str(exc))
        _sync_lead_status(db, task, "failed")
        db.commit()
        return {"task_id": task.id, "status": "failed", "error": str(exc)}

    if outcome.status == "failed":
        crawl_tasks_crud.mark_failed(db, task=task, error=outcome.error)
        _sync_lead_status(db, task, "failed")
        db.commit()
        return {"task_id": task.id, "status": "failed", "error": outcome.error}

    crawl_tasks_crud.mark_success(
        db, task=task, emails=outcome.emails, pages_crawled=outcome.pages_crawled
    )
    lead = leads_crud.get(db, task.lead_id) if task.lead_id else None
    if lead is not None:
        lead.contact_emails = outcome.emails
        if outcome.emails and not lead.contact_email:
            lead.contact_email = outcome.emails[0]
        lead.pages_crawled = outcome.pages_crawled
        lead.website_content = outcome.text
        lead.crawl_time = outcome.crawl_time
        # Store a text sample so the AI analyser has material to score.
        if outcome.text:
            lead.description = (lead.description or "") + "\n" + outcome.text
            lead.description = lead.description[-4000:]
        lead.crawl_status = "success"
        db.add(lead)
    db.commit()
    return {
        "task_id": task.id,
        "status": "success",
        "emails": outcome.emails,
        "pages_crawled": outcome.pages_crawled,
    }


def process_pending(
    db: Session, *, limit: int = 100, crawler: Optional[WebsiteCrawler] = None
) -> dict:
    """Process all currently ``pending`` crawl tasks."""
    crawler = crawler or WebsiteCrawler()
    tasks = crawl_tasks_crud.get_pending(db, limit=limit)
    succeeded = skipped = failed = 0
    details = []
    for task in tasks:
        res = process_task(db, task, crawler=crawler)
        details.append(res["task_id"])
        if res["status"] == "success":
            succeeded += 1
        elif res["status"] == "failed":
            failed += 1
        else:
            skipped += 1
    return {
        "tasks_processed": len(tasks),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "details": details,
    }


def crawl_lead(
    db: Session, lead_id: int, crawler: Optional[WebsiteCrawler] = None
) -> dict:
    """Crawl a specific lead (creates a task if none exists)."""
    crawler = crawler or WebsiteCrawler()
    task = crawl_tasks_crud.get_by_lead(db, lead_id)
    lead = leads_crud.get(db, lead_id)
    if lead is None:
        return {"error": "lead not found"}
    if task is None:
        task = crawl_tasks_crud.create(
            db, lead_id=lead.id, domain=lead.domain, url=lead.website, status="pending"
        )
        db.commit()
    return process_task(db, task, crawler=crawler)


def _sync_lead_status(db: Session, task, status: str) -> None:
    if not task.lead_id:
        return
    lead = leads_crud.get(db, task.lead_id)
    if lead is not None:
        lead.crawl_status = status
        db.add(lead)
