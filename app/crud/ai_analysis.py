"""CRUD operations for AIAnalysis (append-only history)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.ai_analysis import AIAnalysis


def create(
    db: Session,
    *,
    lead_id: int,
    casting_need_score: Optional[int] = None,
    sales_priority: Optional[str] = None,
    industry: Optional[str] = None,
    products: Optional[str] = None,
    country: Optional[str] = None,
    buying_signal: Optional[str] = None,
    recommended_contact: Optional[str] = None,
    analysis_json: Optional[dict] = None,
) -> AIAnalysis:
    obj = AIAnalysis(
        lead_id=lead_id,
        casting_need_score=casting_need_score,
        sales_priority=sales_priority,
        industry=industry,
        products=products,
        country=country,
        buying_signal=buying_signal,
        recommended_contact=recommended_contact,
        analysis_json=analysis_json,
    )
    db.add(obj)
    db.flush()
    return obj


def get_by_lead(db: Session, lead_id: int) -> List[AIAnalysis]:
    return (
        db.query(AIAnalysis)
        .filter(AIAnalysis.lead_id == lead_id)
        .order_by(AIAnalysis.id.desc())
        .all()
    )


def get_latest(db: Session, lead_id: int) -> Optional[AIAnalysis]:
    return (
        db.query(AIAnalysis)
        .filter(AIAnalysis.lead_id == lead_id)
        .order_by(AIAnalysis.id.desc())
        .first()
    )
