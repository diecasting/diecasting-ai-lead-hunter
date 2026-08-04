"""CompanyLead ORM model — the core table of the lead-hunter system."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyLead(Base):
    """A B2B lead: a company that may need die-casting services.

    The table stores both raw crawled / imported data and the AI enrichment
    results (score, relevance, summary, signals).
    """

    __tablename__ = "company_leads"

    # --- Identity & source -------------------------------------------------
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    website = Column(String(512), nullable=True, unique=True, index=True)
    domain = Column(String(255), nullable=True, index=True)
    source = Column(String(120), nullable=True)

    # --- Firmographics -----------------------------------------------------
    country = Column(String(120), nullable=True)
    region = Column(String(120), nullable=True)
    industry = Column(String(160), nullable=True)
    description = Column(Text, nullable=True)
    employee_count = Column(Integer, nullable=True)

    # --- Contact -----------------------------------------------------------
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(120), nullable=True)

    # --- AI enrichment -----------------------------------------------------
    ai_score = Column(Float, nullable=True)            # 0-100 fit score
    ai_relevant = Column(Boolean, nullable=True)       # score >= 50
    ai_summary = Column(Text, nullable=True)           # natural-language summary
    ai_signals = Column(Text, nullable=True)           # JSON-encoded list[str]
    ai_analyzed_at = Column(DateTime(timezone=True), nullable=True)

    # --- Timestamps --------------------------------------------------------
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyLead id={self.id} name={self.name!r}>"
