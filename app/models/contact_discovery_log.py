"""ContactDiscoveryLog ORM model (Phase 13.1 Contact Discovery Foundation).

Tracks *when* and *how* a company's contacts / e-mail addresses were last
discovered, so the discovery engines (website crawl, PDF scan, pattern
inference, external enrichment) can avoid re-scanning the same domain
repeatedly and so operators get a visible audit trail.

This is the foundation layer only -- Phase 13.1 adds the log table and the
``discovery_method`` provenance columns on :class:`EmailAddress` /
:class:`Contact`. The actual discovery *engines* (website / PDF / pattern /
external) are built in later sub-phases; until then this model is the single
source of truth for "we already looked here".

Lifecycle:
    RFQ -> Opportunity -> Contact/EmailAddress -> (discovery logged here)

Conventions (mirrors Phase 12.x):
  * ``company_id`` is an ownership FK (CASCADE) -- deleting a lead removes its
    discovery history.
  * ``method`` / ``status`` use small string vocabularies defined below.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Discovery method vocabulary
# ---------------------------------------------------------------------------
DISCOVERY_METHOD_WEBSITE = "website"   # crawled the company website
DISCOVERY_METHOD_PDF = "pdf"           # mined a PDF catalog / technical doc
DISCOVERY_METHOD_PATTERN = "pattern"   # inferred from a naming pattern + domain
DISCOVERY_METHOD_EXTERNAL = "external"  # third-party enrichment provider (future)

DISCOVERY_METHODS = [
    DISCOVERY_METHOD_WEBSITE,
    DISCOVERY_METHOD_PDF,
    DISCOVERY_METHOD_PATTERN,
    DISCOVERY_METHOD_EXTERNAL,
]

# ---------------------------------------------------------------------------
# Scan status vocabulary
# ---------------------------------------------------------------------------
DISCOVERY_STATUS_DONE = "done"
DISCOVERY_STATUS_FAILED = "failed"
DISCOVERY_STATUS_SKIPPED = "skipped"

DISCOVERY_STATUSES = [
    DISCOVERY_STATUS_DONE,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_SKIPPED,
]


class ContactDiscoveryLog(Base):
    """A single discovery scan record for one company / domain / method."""

    __tablename__ = "contact_discovery_logs"
    __table_args__ = (
        Index(
            "ix_contact_discovery_logs_company_method",
            "company_id",
            "method",
        ),
        Index(
            "ix_contact_discovery_logs_company_domain_method",
            "company_id",
            "domain",
            "method",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    domain = Column(String(255), nullable=False, index=True)
    method = Column(
        String(20),
        nullable=False,
        default=DISCOVERY_METHOD_WEBSITE,
        server_default=DISCOVERY_METHOD_WEBSITE,
    )
    scanned_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    contacts_found = Column(Integer, nullable=False, default=0, server_default="0")
    emails_found = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(
        String(20),
        nullable=False,
        default=DISCOVERY_STATUS_DONE,
        server_default=DISCOVERY_STATUS_DONE,
    )
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # ORM-side cascade so deleting a CompanyLead also removes its discovery
    # history even on backends that do not enforce DB-level FK cascades (e.g.
    # SQLite in the test harness). Mirrors the Quote.lines cascade pattern.
    company = relationship("CompanyLead", back_populates="discovery_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ContactDiscoveryLog id={self.id} company_id={self.company_id} "
            f"domain={self.domain!r} method={self.method!r} "
            f"status={self.status!r}>"
        )
