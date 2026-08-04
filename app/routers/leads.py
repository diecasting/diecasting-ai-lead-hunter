"""Lead API routes: CRUD plus crawl/ingest, AI-analysis, and search endpoints."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.analyzer import run_analysis
from app.config import settings
from app.crawler.runner import process_pending
from app.crud import leads as crud
from app.database import get_db
from app.models.lead import CompanyLead
from app.schemas.lead import CompanyLeadCreate, CompanyLeadRead, CompanyLeadUpdate
from app.search.service import SearchService

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=List[CompanyLeadRead])
def list_leads(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    relevant_only: bool = False,
    priority: str = Query(None, description="Filter by sales_priority: HIGH/MEDIUM/LOW"),
):
    query = db.query(CompanyLead)
    if relevant_only:
        query = query.filter(CompanyLead.ai_relevant.is_(True))
    if priority:
        query = query.filter(CompanyLead.sales_priority == priority.upper())
    return (
        query.order_by(CompanyLead.id.desc()).offset(skip).limit(limit).all()
    )


@router.post("", response_model=CompanyLeadRead, status_code=201)
def create_lead(payload: CompanyLeadCreate, db: Session = Depends(get_db)):
    if payload.website and crud.get_by_website(db, payload.website):
        raise HTTPException(status_code=409, detail="Lead with this website already exists")
    return crud.create(db, obj_in=payload)


@router.get("/{lead_id}", response_model=CompanyLeadRead)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return obj


@router.patch("/{lead_id}", response_model=CompanyLeadRead)
def update_lead(lead_id: int, payload: CompanyLeadUpdate, db: Session = Depends(get_db)):
    obj = crud.get(db, lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return crud.update(db, db_obj=obj, obj_in=payload)


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    obj = crud.remove(db, lead_id=lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")


@router.post("/ingest", response_model=List[CompanyLeadRead], status_code=201)
def ingest_from_web(
    db: Session = Depends(get_db),
    query: str = Query("aluminum die casting manufacturer"),
    country: str = Query("us"),
    max_results: int = Query(20, ge=1, le=50),
):
    """Search Google for die-casting companies and persist them as leads.

    Creates ``company_leads`` (dedup by homepage) plus a ``crawl_tasks`` row
    each, ready for the crawler / scheduler. Requires Playwright browsers.
    """
    try:
        report = SearchService().run_search(
            db, query, country=country, max_results=max_results
        )
    except Exception as exc:  # pragma: no cover - depends on network/browser
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")

    leads = [crud.get(db, lid) for lid in report["created_lead_ids"]]
    leads = [l for l in leads if l is not None]
    return leads


@router.post("/{lead_id}/analyze", response_model=CompanyLeadRead)
def analyze_lead(lead_id: int, db: Session = Depends(get_db)):
    """Run the AI analysis / casting-need scoring on a single lead.

    Works without an OpenAI key (deterministic rule-based scoring). When a key
    is configured, the English summary is enriched by the LLM.
    """
    obj = crud.get(db, lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        run_analysis(db, obj, crawled_text=obj.description or "")
    except Exception as exc:  # pragma: no cover - depends on OpenAI
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {exc}")
    db.refresh(obj)
    return obj


@router.post("/crawl/pending", response_model=dict)
def crawl_pending(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Crawl all currently ``pending`` crawl tasks (or use the scheduler)."""
    try:
        from app.crawler.website_crawler import WebsiteCrawler

        report = process_pending(db, limit=limit, crawler=WebsiteCrawler())
    except Exception as exc:  # pragma: no cover - depends on browser/network
        raise HTTPException(status_code=502, detail=f"Crawl failed: {exc}")
    return report


# ---------------------------------------------------------------------------
# Phase 2.3: Industrial AI Lead Intelligence
# ---------------------------------------------------------------------------
@router.get("/high-priority", response_model=List[CompanyLeadRead])
def get_high_priority_leads(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Return the most sales-worthy leads, sorted by score descending.

    A lead qualifies as *high-priority* when ``sales_priority`` is ``HIGH``
    (best need-score ≥ 80). If fewer than ``limit`` HIGH leads exist, the
    remaining slots are filled with MEDIUM leads so the sales team always
    has a actionable shortlist.
    """
    high = (
        db.query(CompanyLead)
        .filter(CompanyLead.sales_priority == "HIGH")
        .order_by(CompanyLead.ai_score.desc().nullslast(), CompanyLead.id.desc())
        .limit(limit)
        .all()
    )
    remaining = limit - len(high)
    if remaining > 0:
        high_ids = {l.id for l in high}
        medium = (
            db.query(CompanyLead)
            .filter(
                CompanyLead.sales_priority == "MEDIUM",
                CompanyLead.id.notin_(high_ids) if high_ids else True,
            )
            .order_by(CompanyLead.ai_score.desc().nullslast(), CompanyLead.id.desc())
            .limit(remaining)
            .all()
        )
        high.extend(medium)
    return high


@router.post("/{lead_id}/intelligence", response_model=CompanyLeadRead)
def run_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
    crawl: bool = Query(True, description="Crawl website content before analysis"),
    extract_pdfs: bool = Query(
        True, description="Discover and extract PDF documents (catalogs/brochures)"
    ),
):
    """Full Phase 2.3 intelligence pipeline for a single lead.

    Steps:
    1. (optional) Crawl the company website → structured page text.
    2. (optional) Discover & extract PDF documents → capability signals.
    3. Run the AI analysis (rule-based scoring + optional LLM summary).
    4. Compute the final ``sales_priority`` via the ranking engine.

    The lead's intelligence fields (scores, materials, processes,
    buying_signal, business_type, ai_summary, …) are updated in place.
    """
    obj = crud.get(db, lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    pdf_text = ""

    # Step 1: crawl website content (if enabled and website exists).
    if crawl and obj.website:
        try:
            from app.crawler.website_crawler import WebsiteCrawler

            crawler = WebsiteCrawler()
            result = crawler.crawl(obj.website)
            # result is a CrawlResult dataclass with .text_content and .pages_found
            website_text = getattr(result, "text_content", "") or ""
            if website_text:
                obj.website_content = website_text[:50000]
                obj.pages_crawled = getattr(result, "pages_found", 0) or 0
                from datetime import datetime, timezone
                obj.crawl_status = "completed"
                obj.crawl_time = datetime.now(timezone.utc)
                db.add(obj)
                db.commit()
        except Exception as exc:  # pragma: no cover - depends on browser/network
            # Crawl failure should not block the analysis pipeline.
            obj.crawl_status = "failed"
            db.add(obj)
            db.commit()

    # Step 2: extract PDF documents (if enabled).
    if extract_pdfs and obj.website:
        try:
            from app.crawler.pdf_extractor import PDFExtractor

            extractor = PDFExtractor()
            home_html = obj.website_content or ""
            pdf_result = extractor.extract_for_lead(db, obj, home_html=home_html)
            # Merge PDF text into the analysis input.
            from app.crud import company_documents as doc_crud
            docs = doc_crud.get_by_lead(db, obj.id)
            pdf_text = " ".join(d.content or "" for d in docs)
        except Exception:  # pragma: no cover - depends on network/PDF libs
            pass

    # Step 3 + 4: AI analysis + ranking.
    try:
        crawled_text = " ".join(
            t for t in [obj.website_content or "", pdf_text] if t
        )
        run_analysis(db, obj, crawled_text=crawled_text)
    except Exception as exc:  # pragma: no cover - depends on OpenAI
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {exc}")

    db.refresh(obj)
    return obj
