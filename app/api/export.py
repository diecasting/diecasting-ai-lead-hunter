"""Export API routes (Phase 2.2 / 2.6 / 2.5).

``GET /export/csv`` builds ``sales_leads.csv`` with the sales-team friendly
columns (company, country, website, industry, products, email, score, reason,
priority) plus Phase 2.5 CRM fields (lead_status, email_status, last_contact,
next_followup). Saves a copy under ``settings.export_dir`` and streams it back.
"""
import csv
import io
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import ai_analysis as ai_crud
from app.crud import outreach as outreach_crud
from app.database import get_db
from app.models.lead import CompanyLead

router = APIRouter(prefix="/export", tags=["export"])

EXPORT_FIELDS = [
    "company",
    "country",
    "website",
    "industry",
    "products",
    "email",
    "score",
    "reason",
    "priority",
    "lead_status",
    "email_status",
    "last_contact",
    "next_followup",
]


def _latest_message_status(db: Session, lead_id: int) -> str:
    msgs = outreach_crud.get_by_lead(db, lead_id)
    if not msgs:
        return ""
    return msgs[0].status  # most recent first


def _build_rows(db: Session) -> List[dict]:
    leads = db.query(CompanyLead).order_by(CompanyLead.id.desc()).all()
    rows: List[dict] = []
    for lead in leads:
        analysis = ai_crud.get_latest(db, lead.id) if lead.id is not None else None

        emails = list(lead.contact_emails or [])
        if not emails and lead.contact_email:
            emails = [lead.contact_email]

        products = (analysis.products if analysis else None) or lead.industry or ""
        reason = (analysis.buying_signal if analysis else None) or (
            lead.ai_summary or ""
        )

        # Phase 2.5 CRM fields
        latest_msg = outreach_crud.get_by_lead(db, lead.id)
        email_status = latest_msg[0].status if latest_msg else ""
        last_contact = lead.last_activity_time.isoformat() if lead.last_activity_time else ""
        next_followup = lead.next_followup_date.isoformat() if lead.next_followup_date else ""

        rows.append(
            {
                "company": lead.name or "",
                "country": lead.country or "",
                "website": lead.website or "",
                "industry": lead.industry or "",
                "products": products,
                "email": emails[0] if emails else "",
                "score": lead.casting_need_score if lead.casting_need_score is not None else "",
                "reason": reason,
                "priority": lead.sales_priority or "",
                "lead_status": lead.lead_status or "new",
                "email_status": email_status,
                "last_contact": last_contact,
                "next_followup": next_followup,
            }
        )
    return rows


def _render_csv(rows: List[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


@router.get("/csv", response_model=None)
def export_csv(db: Session = Depends(get_db)):
    """Generate ``sales_leads.csv`` and stream it as a downloadable file."""
    rows = _build_rows(db)
    csv_text = _render_csv(rows)

    # Persist a copy for audit / offline use.
    try:
        os.makedirs(settings.export_dir, exist_ok=True)
        filename = f"sales_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = os.path.join(settings.export_dir, filename)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_text)
        # Also keep a stable "latest" copy.
        latest = os.path.join(settings.export_dir, "sales_leads.csv")
        with open(latest, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_text)
    except OSError:  # pragma: no cover - export dir may be read-only
        pass

    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_leads.csv"},
    )
