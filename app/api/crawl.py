"""Crawl API routes (Phase 2.2).

Endpoints
---------
* ``POST /crawl/{lead_id}``  — start crawling a lead's website.
* ``GET  /crawl/status/{lead_id}`` — current crawl status / result summary.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crawler.runner import crawl_lead
from app.crawler.website_crawler import WebsiteCrawler
from app.crud import leads as crud
from app.database import get_db
from app.models.lead import CompanyLead

router = APIRouter(prefix="/crawl", tags=["crawl"])


@router.post("/{lead_id}", response_model=dict)
def start_crawl(lead_id: int, db: Session = Depends(get_db)):
    """Start crawling the website for a lead (creates/uses its crawl task)."""
    lead = crud.get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.crawl_status = "running"
    db.add(lead)
    db.commit()
    try:
        res = crawl_lead(db, lead_id, crawler=WebsiteCrawler())
    except Exception as exc:  # pragma: no cover - depends on browser/network
        lead.crawl_status = "failed"
        db.add(lead)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Crawl failed: {exc}")

    db.refresh(lead)
    return {
        "lead_id": lead_id,
        "status": res.get("status"),
        "pages_crawled": res.get("pages_crawled"),
        "emails": res.get("emails", []),
        "error": res.get("error"),
    }


@router.get("/status/{lead_id}", response_model=dict)
def crawl_status(lead_id: int, db: Session = Depends(get_db)):
    """Return the crawl status, pages crawled, e-mails and last update time."""
    lead = crud.get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    emails = list(lead.contact_emails or [])
    if not emails and lead.contact_email:
        emails = [lead.contact_email]

    return {
        "status": lead.crawl_status,
        "pages": lead.pages_crawled,
        "emails": emails,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }
