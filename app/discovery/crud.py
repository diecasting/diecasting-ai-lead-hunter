"""CRUD helpers for CompanyDiscovery (Phase 5 Stage 1)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.company_discovery import CompanyDiscovery


def create(
    db: Session,
    *,
    company_name: str,
    website: Optional[str] = None,
    country: Optional[str] = None,
    industry: Optional[str] = None,
    detected_materials: Optional[str] = None,
    detected_processes: Optional[str] = None,
    buying_signals: Optional[str] = None,
    discovery_source: str = "url_analysis",
    confidence_score: Optional[int] = None,
    lead_score: Optional[int] = None,
    recommended_contact_role: Optional[str] = None,
    profile: Optional[str] = None,
) -> CompanyDiscovery:
    obj = CompanyDiscovery(
        company_name=company_name,
        website=website,
        country=country,
        industry=industry,
        detected_materials=detected_materials,
        detected_processes=detected_processes,
        buying_signals=buying_signals,
        discovery_source=discovery_source,
        confidence_score=confidence_score,
        lead_score=lead_score,
        recommended_contact_role=recommended_contact_role,
        profile=profile,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, discovery_id: int) -> Optional[CompanyDiscovery]:
    return (
        db.query(CompanyDiscovery)
        .filter(CompanyDiscovery.id == discovery_id)
        .first()
    )


def list_all(db: Session, *, limit: int = 50) -> List[CompanyDiscovery]:
    return (
        db.query(CompanyDiscovery)
        .order_by(CompanyDiscovery.id.desc())
        .limit(limit)
        .all()
    )


def link_to_lead(
    db: Session, obj: CompanyDiscovery, lead_id: int
) -> CompanyDiscovery:
    """Attach a discovery record to the CRM lead it produced."""
    obj.lead_id = lead_id
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
