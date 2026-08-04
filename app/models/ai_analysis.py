"""AIAnalysis ORM model — append-only history of AI lead analyses.

Each run of the scoring / analysis pipeline writes a new row here so we keep a
full audit trail of how a lead's ``casting_need_score`` and ``sales_priority``
evolved over time. The latest values are also denormalised onto ``CompanyLead``
for fast querying and CSV export.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import declarative_base

from app.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id"), nullable=False, index=True
    )

    casting_need_score = Column(Integer, nullable=True)      # 0-100
    sales_priority = Column(String(10), nullable=True)       # HIGH / MEDIUM / LOW
    industry = Column(String(160), nullable=True)
    products = Column(Text, nullable=True)
    country = Column(String(120), nullable=True)
    buying_signal = Column(Text, nullable=True)
    recommended_contact = Column(String(255), nullable=True)

    analysis_json = Column(JSON, nullable=True)  # full structured output
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AIAnalysis id={self.id} lead_id={self.lead_id} "
            f"score={self.casting_need_score}>"
        )
