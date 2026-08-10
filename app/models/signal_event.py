"""Phase 16.1: Intent Event Foundation — SignalEvent model.

A :class:`SignalEvent` is a single, timestamped, source-attributed *raw* buying
-intent observation about an entity. It is the fine-grained event ledger that
future intent-detection sources (Google search, job postings, website changes,
RFQ keywords, product launches — Phase 16.2) will append to.

It deliberately sits *below* the aggregated per-lead :class:`ConversionSignal`
snapshot and the legacy ``CompanyLead.buying_signal`` string: those are derived
views, this is the source-of-truth event stream.

Design constraints (Phase 16.1 foundation):
  * **Entity-agnostic linkage** — a signal may attach to a ``CompanyLead``
    (prospect), an ``Opportunity`` (deal), or a ``Contact`` (person). Exactly
    one of the three FKs is normally populated; all are nullable + SET NULL so
    deleting an underlying entity never orphans a signal row.
  * **Signed value** — ``value`` is a SIGNED intent / strength number in the
    range ``-100 .. +100`` (negative = deterrent / churn risk, positive =
    buying signal). ``confidence`` is the unsigned 0..100 source-reliability.
  * **Deterministic dedup** — ``dedup_key`` is a SHA-1 of the entity scope +
    source + signal_type + external_id, enforced unique at the DB level so
    re-ingesting the same observation updates in place rather than duplicating.
  * **TTL** — ``expires_at`` lets stale signals age out of scoring; ``is_active``
    is the soft-toggle used by the expire job.

No scoring, no external API calls, no dashboard changes live here — this is the
storage + ingestion foundation only.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Signal source vocabulary (extensible; Phase 16.2 adds one adapter per source)
# ---------------------------------------------------------------------------
SOURCE_WEBSITE_CHANGE = "website_change"
SOURCE_REPLY_INTENT = "reply_intent"
SOURCE_MANUAL = "manual"
SOURCE_GOOGLE_SEARCH = "google_search"
SOURCE_JOB_POSTING = "job_posting"
SOURCE_RFQ_KEYWORD = "rfq_keyword"
SOURCE_PRODUCT_LAUNCH = "product_launch"
SOURCE_OTHER = "other"

SIGNAL_SOURCES = [
    SOURCE_WEBSITE_CHANGE,
    SOURCE_REPLY_INTENT,
    SOURCE_MANUAL,
    SOURCE_GOOGLE_SEARCH,
    SOURCE_JOB_POSTING,
    SOURCE_RFQ_KEYWORD,
    SOURCE_PRODUCT_LAUNCH,
    SOURCE_OTHER,
]


# ---------------------------------------------------------------------------
# Intent category vocabulary
# ---------------------------------------------------------------------------
INTENT_PURCHASE = "purchase"
INTENT_HIRING = "hiring"
INTENT_EXPANSION = "expansion"
INTENT_REPLACEMENT = "replacement"
INTENT_RESEARCH = "research"
INTENT_DETERRENT = "deterrent"

INTENT_CATEGORIES = [
    INTENT_PURCHASE,
    INTENT_HIRING,
    INTENT_EXPANSION,
    INTENT_REPLACEMENT,
    INTENT_RESEARCH,
    INTENT_DETERRENT,
]


# ---------------------------------------------------------------------------
# Signed value bounds
# ---------------------------------------------------------------------------
SIGNAL_VALUE_MIN = -100
SIGNAL_VALUE_MAX = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clamp_signal_value(value):
    """Clamp a raw signal value into the signed -100..100 range.

    ``None`` passes through (the column is nullable). Any out-of-range number is
    pinned to the nearest bound — deterministic, no exceptions.
    """
    if value is None:
        return None
    return max(SIGNAL_VALUE_MIN, min(SIGNAL_VALUE_MAX, int(value)))


def clamp_confidence(value):
    """Clamp a confidence score into the unsigned 0..100 range."""
    if value is None:
        return None
    return max(0, min(100, int(value)))


class SignalEvent(Base):
    """A single buying-intent observation about a company / opportunity / contact."""

    __tablename__ = "signal_events"

    id = Column(Integer, primary_key=True, index=True)

    # --- Entity linkage (nullable SET NULL; normally exactly one is set) -----
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Signal identity -----------------------------------------------------
    source = Column(String(20), nullable=False, index=True)
    signal_type = Column(String(40), nullable=False, index=True)
    intent_category = Column(String(20), nullable=True, index=True)

    # --- Strength / reliability ---------------------------------------------
    # SIGNED intent strength in -100..+100 (negative = deterrent).
    value = Column(Integer, nullable=True, index=True)
    # Unsigned 0..100 source-reliability / detection confidence.
    confidence = Column(Integer, nullable=True)

    # --- Evidence / provenance ----------------------------------------------
    raw_value = Column(Text, nullable=True)          # snippet / URL / job title
    detected_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default="1", index=True
    )

    # --- Deterministic upsert key -------------------------------------------
    external_id = Column(String(255), nullable=True, index=True)
    # SHA-1 of (entity scope | source | signal_type | external_id); unique.
    dedup_key = Column(String(64), nullable=False, unique=True, index=True)

    # --- Misc ----------------------------------------------------------------
    metadata_json = Column(Text, nullable=True)      # free-form JSON context
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # --- Relationships (lazy; populated only when explicitly joined) ----------
    # Backrefs ``CompanyLead.signal_events`` / ``Opportunity.signal_events`` /
    # ``Contact.signal_events``. These give ORM-level SET NULL on parent delete
    # (mirrors ConversionSignal/Opportunity) so deletion never orphans a signal
    # even on SQLite where PRAGMA foreign_keys is OFF in tests.
    company = relationship("CompanyLead", backref="signal_events")
    opportunity = relationship("Opportunity", backref="signal_events")
    contact = relationship("Contact", backref="signal_events")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SignalEvent id={self.id} source={self.source!r} "
            f"type={self.signal_type!r} value={self.value}>"
        )
