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
from sqlalchemy.orm import declarative_base, relationship

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
    # Phase 4 Stage 3.5: how this lead entered the system (import | manual |
    # search | ...). The database default is "import".
    lead_source = Column(
        String(50), nullable=False, default="import", server_default="import", index=True
    )

    # --- Firmographics -----------------------------------------------------
    country = Column(String(120), nullable=True)
    region = Column(String(120), nullable=True)
    industry = Column(String(160), nullable=True)
    description = Column(Text, nullable=True)
    employee_count = Column(Integer, nullable=True)

    # --- Contact -----------------------------------------------------------
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(120), nullable=True)
    contact_name = Column(String(255), nullable=True)  # Phase 4 Stage 3.5

    # --- AI enrichment -----------------------------------------------------
    ai_score = Column(Float, nullable=True)            # 0-100 fit score

    # Phase 6.5: e-mail verification (MX / syntax / SMTP deliverability).
    # Status is one of: valid | invalid | unknown. `invalid` (e.g. no MX
    # record) blocks outreach sends to the contact address.
    email_status = Column(
        String(20), nullable=True, default="unknown", server_default="unknown", index=True
    )
    email_confidence_score = Column(
        Integer, nullable=True, index=True
    )  # 0-100 confidence to deliver
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
    )  # new | contacted | sent | replied | qualified | rfq | customer | closed (Phase 4.6)
    last_activity_time = Column(DateTime(timezone=True), nullable=True)
    next_followup_date = Column(DateTime(timezone=True), nullable=True)

    # Phase 16.3: Intent Aggregation Layer — deterministic snapshot of the
    # signal_events ledger (populated by scripts/recompute_intent.py / API).
    # NOT derived from lead_score / sales_priority; aggregation is read-only
    # w.r.t. those fields. All nullable so the snapshot can fill incrementally.
    buying_intent_score = Column(Integer, nullable=True, index=True)  # 0-100
    timing_score = Column(Integer, nullable=True, index=True)         # 0-100
    intent_temperature = Column(String(10), nullable=True, index=True)  # HOT/WARM/COOL/COLD/NONE
    last_signal_at = Column(DateTime(timezone=True), nullable=True, index=True)
    intent_source_count = Column(Integer, nullable=True)
    intent_sources = Column(Text, nullable=True)  # JSON-encoded list[str] of source ids

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

    # --- Phase 13.1: discovery history (cascade removes logs with the lead) -
    discovery_logs = relationship(
        "ContactDiscoveryLog",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyLead id={self.id} name={self.name!r}>"
