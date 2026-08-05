"""CompanyLead ORM model — the core table of the lead-hunter system."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
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

    # Phase 2: dedicated casting-need scoring
    casting_need_score = Column(Integer, nullable=True, index=True)  # 0-100
    cnc_need_score = Column(Integer, nullable=True, index=True)      # 0-100
    tooling_need_score = Column(Integer, nullable=True, index=True)  # 0-100
    sales_priority = Column(String(10), nullable=True, index=True)   # HIGH/MEDIUM/LOW

    # Phase 2.3: industrial lead intelligence
    business_type = Column(String(80), nullable=True)        # Manufacturer / Trader / Supplier
    materials = Column(Text, nullable=True)                  # detected material keywords
    manufacturing_process = Column(Text, nullable=True)      # detected process keywords
    buying_signal = Column(Text, nullable=True)              # HIGH / MEDIUM / LOW (+ detail)
    contact_role = Column(String(120), nullable=True)       # primary contact role/title (Phase 4)

    # Phase 2.5: CRM pipeline
    lead_status = Column(
        String(20), nullable=False, default="new", server_default="new", index=True
    )  # new | qualified | email_generated | approved | contacted | replied | customer | lost
    last_activity_time = Column(DateTime(timezone=True), nullable=True)
    next_followup_date = Column(DateTime(timezone=True), nullable=True)

    # Phase 3 Stage 1: CRM data model upgrade
    do_not_contact = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    bounce_count = Column(
        Integer, nullable=False, default=0, server_default="0", index=True
    )
    acquisition_channel = Column(String(120), nullable=True, index=True)

    # Phase 3 Stage 3: AI lead scoring & prioritization
    # Composite 0-100 fit score combining company fit, website intent,
    # procurement signal, contact quality and PDF signal.
    lead_score = Column(Integer, nullable=True, index=True)
    lead_score_breakdown = Column(Text, nullable=True)  # JSON-encoded breakdown
    priority = Column(String(10), nullable=True, index=True)  # HIGH/MEDIUM/LOW

    # --- Crawl state -------------------------------------------------------
    crawl_status = Column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    contact_emails = Column(JSON, nullable=True)          # list[str] of company e-mails
    pages_crawled = Column(Integer, nullable=False, default=0, server_default="0")
    website_content = Column(Text, nullable=True)         # concatenated crawled text
    crawl_time = Column(DateTime(timezone=True), nullable=True)

    # --- Timestamps --------------------------------------------------------
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyLead id={self.id} name={self.name!r}>"
