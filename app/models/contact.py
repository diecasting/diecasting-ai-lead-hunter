"""Contact ORM model (Phase 3 Stage 1, extended Phase 8.5).

A ``Contact`` is an individual person at a ``CompanyLead`` company — the human
recipient of outreach (as opposed to the company-level ``contact_email``). This
supports multi-threading an account (e.g. Purchasing + Engineering) and stores
per-contact deliverability / opt-out state.

Phase 8.5 (Contact Intelligence Engine) adds the *intelligence* columns:
``source`` (provenance), ``title_category`` / ``seniority`` (title
classification), ``purchasing_score`` / ``priority`` (purchasing priority
scoring) and ``email_address_id`` (link back to a discovered
:class:`EmailAddress`). All additions are nullable with sane defaults so the
existing CRM behaviour is fully preserved.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Provenance (where the contact came from)
# ---------------------------------------------------------------------------
SOURCE_WEBSITE = "website"          # extracted by crawling the company website
SOURCE_CRM = "crm"                  # already on the lead (contact_email / role)
SOURCE_EMAIL_PATTERN = "email_pattern"  # derived from a discovered personal e-mail
SOURCE_MANUAL = "manual"            # entered / verified explicitly by an operator

CONTACT_SOURCES = [
    SOURCE_WEBSITE,
    SOURCE_CRM,
    SOURCE_EMAIL_PATTERN,
    SOURCE_MANUAL,
]

# ---------------------------------------------------------------------------
# Title classification vocabulary
# ---------------------------------------------------------------------------
CATEGORY_PROCUREMENT = "procurement"
CATEGORY_ENGINEERING = "engineering"
CATEGORY_EXECUTIVE = "executive"
CATEGORY_OPERATIONS = "operations"
CATEGORY_SALES = "sales"
CATEGORY_FINANCE = "finance"
CATEGORY_OTHER = "other"

TITLE_CATEGORIES = [
    CATEGORY_PROCUREMENT,
    CATEGORY_ENGINEERING,
    CATEGORY_EXECUTIVE,
    CATEGORY_OPERATIONS,
    CATEGORY_SALES,
    CATEGORY_FINANCE,
    CATEGORY_OTHER,
]

# ---------------------------------------------------------------------------
# Seniority vocabulary
# ---------------------------------------------------------------------------
SENIORITY_EXECUTIVE = "executive"
SENIORITY_SENIOR = "senior"
SENIORITY_MID = "mid"
SENIORITY_JUNIOR = "junior"
SENIORITY_UNKNOWN = "unknown"

SENIORITY_LEVELS = [
    SENIORITY_EXECUTIVE,
    SENIORITY_SENIOR,
    SENIORITY_MID,
    SENIORITY_JUNIOR,
    SENIORITY_UNKNOWN,
]

# ---------------------------------------------------------------------------
# Purchasing priority vocabulary
# ---------------------------------------------------------------------------
PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

PRIORITIES = [PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW]


class Contact(Base):
    """A person at a lead company who can be contacted directly."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(120), nullable=True)
    role = Column(String(160), nullable=True)          # e.g. Purchasing Manager
    title = Column(String(160), nullable=True)         # free-text job title
    is_primary = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    do_not_contact = Column(
        Boolean, nullable=False, default=False, server_default="0", index=True
    )

    # --- Phase 8.5: Contact Intelligence fields (additive) -----------------
    # Provenance of the contact record.
    source = Column(String(40), nullable=True, default=SOURCE_WEBSITE)
    # Classified job-title category + seniority tier.
    title_category = Column(String(40), nullable=True, index=True)
    seniority = Column(String(20), nullable=True)
    # Purchasing-decision priority: 0-100 score + derived label.
    purchasing_score = Column(Integer, nullable=True, index=True)
    priority = Column(String(20), nullable=True, index=True)
    # Link back to a discovered corporate e-mail (Phase 8 EmailAddress).
    email_address_id = Column(
        Integer,
        ForeignKey("email_addresses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # When this contact was first discovered by the engine.
    discovered_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 13.1: how the contact was discovered (website / pdf / pattern /
    # external). Nullable additive column; defaults to "website" for contacts
    # produced by the existing crawler. Distinct from ``source`` (high-level
    # origin) -- this is the discovery *engine* that found it. Reuses the
    # DISCOVERY_METHOD_* vocabulary from ``app.models.email_address``.
    discovery_method = Column(
        String(20), nullable=True, default="website",
        server_default="website", index=True,
    )

    # Phase 13.2: discovery-engine enrichment (additive, nullable, indexed).
    # The precise URL the contact was mined from (a website page or a PDF doc).
    source_url = Column(String(512), nullable=True, index=True)
    # Deterministic 0-100 discovery quality score produced by the engine
    # (verification + source + role + pattern signals). Null until scored.
    discovery_score = Column(Integer, nullable=True, index=True)
    # Confidence label derived from ``discovery_score`` (high / medium / low).
    confidence = Column(String(20), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Contact id={self.id} lead_id={self.lead_id} email={self.email!r}>"
