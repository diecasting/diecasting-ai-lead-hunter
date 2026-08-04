"""CRUD operations for CrawlTask."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.crawl_task import CrawlTask


def create(
    db: Session,
    *,
    lead_id: Optional[int] = None,
    domain: Optional[str] = None,
    url: Optional[str] = None,
    status: str = "pending",
    max_retries: int = 3,
) -> CrawlTask:
    obj = CrawlTask(
        lead_id=lead_id,
        domain=domain,
        url=url,
        status=status,
        max_retries=max_retries,
    )
    db.add(obj)
    db.flush()
    return obj


def get_pending(db: Session, *, limit: int = 100) -> List[CrawlTask]:
    return (
        db.query(CrawlTask)
        .filter(CrawlTask.status == "pending")
        .order_by(CrawlTask.id.asc())
        .limit(limit)
        .all()
    )


def get_by_lead(db: Session, lead_id: int) -> Optional[CrawlTask]:
    return (
        db.query(CrawlTask)
        .filter(CrawlTask.lead_id == lead_id)
        .order_by(CrawlTask.id.desc())
        .first()
    )


def get_multi(
    db: Session,
    *,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
) -> List[CrawlTask]:
    query = db.query(CrawlTask)
    if status:
        query = query.filter(CrawlTask.status == status)
    return query.order_by(CrawlTask.id.desc()).offset(skip).limit(limit).all()


def mark_running(db: Session, task: CrawlTask) -> CrawlTask:
    task.status = "running"
    db.add(task)
    db.flush()
    return task


def mark_success(
    db: Session, *, task: CrawlTask, emails: Optional[list] = None, pages_crawled: int = 0
) -> CrawlTask:
    import json

    task.status = "success"
    task.emails = json.dumps(emails or [], ensure_ascii=False)
    task.pages_crawled = pages_crawled
    task.last_error = None
    db.add(task)
    db.flush()
    return task


def mark_failed(db: Session, *, task: CrawlTask, error: str) -> CrawlTask:
    task.retry_count = (task.retry_count or 0) + 1
    if task.retry_count >= task.max_retries:
        task.status = "failed"
    else:
        task.status = "pending"  # re-enqueue for the next run
    task.last_error = error[:2000]
    db.add(task)
    db.flush()
    return task
