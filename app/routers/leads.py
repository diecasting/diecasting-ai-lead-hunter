"""Lead API routes: CRUD plus crawl/ingest and AI-analysis endpoints."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.analyzer import analyze_company, analysis_to_columns
from app.config import settings
from app.crawler.crawler import crawl as run_crawl
from app.crud import leads as crud
from app.database import get_db
from app.models.lead import CompanyLead
from app.schemas.lead import CompanyLeadCreate, CompanyLeadRead, CompanyLeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=List[CompanyLeadRead])
def list_leads(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    relevant_only: bool = False,
):
    return crud.get_multi(db, skip=skip, limit=limit, relevant_only=relevant_only)


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
    max_results: int = Query(10, ge=1, le=50),
):
    """Crawl the web for die-casting companies and persist them as leads.

    De-duplicates by website. Requires Playwright browsers to be installed.
    """
    try:
        companies = run_crawl(query=query, max_results=max_results)
    except Exception as exc:  # pragma: no cover - depends on network/browser
        raise HTTPException(status_code=502, detail=f"Crawl failed: {exc}")

    created: List[CompanyLead] = []
    for company in companies:
        website = company.get("website")
        if website and crud.get_by_website(db, website):
            continue
        payload = CompanyLeadCreate(**company)
        created.append(crud.create(db, obj_in=payload))
    return created


@router.post("/{lead_id}/analyze", response_model=CompanyLeadRead)
def analyze_lead(lead_id: int, db: Session = Depends(get_db)):
    """Run the AI analysis on a single lead and store the enrichment results."""
    obj = crud.get(db, lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not configured")

    lead_dict = {
        "name": obj.name,
        "website": obj.website,
        "industry": obj.industry,
        "description": obj.description,
        "country": obj.country,
        "employee_count": obj.employee_count,
    }
    try:
        analysis = analyze_company(lead_dict)
    except Exception as exc:  # pragma: no cover - depends on OpenAI
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {exc}")

    columns = analysis_to_columns(analysis)
    for field, value in columns.items():
        setattr(obj, field, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
