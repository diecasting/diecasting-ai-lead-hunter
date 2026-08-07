"""Campaign ORM models (Phase 9.5 AI Outreach Campaign Engine).

Two tables power the campaign engine:

  * ``campaigns``          — a named, filterable outreach programme (target
    filters, daily sending cap, quality gate, AI/tone settings, cached
    analytics counters).
  * ``campaign_contacts``  — one row per (campaign, contact / company target).
    This is the *queue*: it carries the selected target, its generated draft,
    its lifecycle status (selected -> queued -> ready -> sent -> replied/rfq),
    ranking and the per-contact analytics timestamps.

Nothing in this module touches the Outreach Engine's ``outreach_messages`` send
pipeline or the CRM — the campaign engine is a targeting / queueing / analytics
layer that hands prepared, approved drafts to the existing outreach workflow.
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Campaign lifecycle states
# ---------------------------------------------------------------------------
CAMPAIGN_STATUS_DRAFT = "draft"
CAMPAIGN_STATUS_ACTIVE = "active"
CAMPAIGN_STATUS_PAUSED = "paused"
CAMPAIGN_STATUS_COMPLETED = "completed"

CAMPAIGN_STATUSES = (
    CAMPAIGN_STATUS_DRAFT,
    CAMPAIGN_STATUS_ACTIVE,
    CAMPAIGN_STATUS_PAUSED,
    CAMPAIGN_STATUS_COMPLETED,
)


# ---------------------------------------------------------------------------
# Campaign-contact (queue) lifecycle states
# ---------------------------------------------------------------------------
CC_STATUS_SELECTED = "selected"   # chosen by the selector, no draft yet
CC_STATUS_QUEUED = "queued"       # approved + staged for sending today
CC_STATUS_READY = "ready"         # draft generated + passed quality gate
CC_STATUS_SENT = "sent"           # handed to outreach / marked sent
CC_STATUS_REPLIED = "replied"     # prospect replied
CC_STATUS_RFQ = "rfq"             # prospect sent a request-for-quote
CC_STATUS_BOUNCED = "bounced"     # delivery failed
CC_STATUS_REJECTED = "rejected"   # draft failed quality gate / excluded

CC_STATUSES = (
    CC_STATUS_SELECTED,
    CC_STATUS_QUEUED,
    CC_STATUS_READY,
    CC_STATUS_SENT,
    CC_STATUS_REPLIED,
    CC_STATUS_RFQ,
    CC_STATUS_BOUNCED,
    CC_STATUS_REJECTED,
)

# Statuses that imply the message was actually sent (counts against the daily
# limit and toward conversion metrics).
CC_SENT_STATUSES = (CC_STATUS_SENT, CC_STATUS_REPLIED, CC_STATUS_RFQ)


class Campaign(Base):
    """A named outreach programme with targeting + sending guard-rails."""

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # --- Targeting filters (all optional) -----------------------------------
    target_industry = Column(String(160), nullable=True, index=True)
    target_country = Column(String(120), nullable=True, index=True)
    # Minimum company priority / sales priority to include (HIGH/MEDIUM/LOW).
    min_priority = Column(String(10), nullable=True, index=True)
    min_sales_priority = Column(String(10), nullable=True, index=True)

    # --- Sending guard-rails ------------------------------------------------
    daily_limit = Column(Integer, nullable=False, default=50, server_default="50")
    quality_gate_min = Column(Integer, nullable=True, index=True)  # min draft quality
    use_ai = Column(Boolean, nullable=False, default=True, server_default="1")
    tone = Column(String(40), nullable=False, default="professional",
                  server_default="professional")

    # --- Lifecycle ----------------------------------------------------------
    status = Column(
        String(20), nullable=False, default=CAMPAIGN_STATUS_DRAFT,
        server_default=CAMPAIGN_STATUS_DRAFT, index=True,
    )

    # --- Cached analytics counters (recomputed from campaign_contacts) ------
    total_targets = Column(Integer, nullable=False, default=0, server_default="0")
    sent_count = Column(Integer, nullable=False, default=0, server_default="0")
    reply_count = Column(Integer, nullable=False, default=0, server_default="0")
    rfq_count = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    contacts = relationship(
        "CampaignContact", back_populates="campaign",
        cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Campaign id={self.id} name={self.name!r} status={self.status!r}>"


class CampaignContact(Base):
    """A single (campaign, target) queue entry."""

    __tablename__ = "campaign_contacts"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # FK links are SET NULL (not CASCADE) so that analytics history survives the
    # deletion of an underlying company / contact / draft.
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    email_address_id = Column(
        Integer,
        ForeignKey("email_addresses.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_id = Column(
        Integer,
        ForeignKey("email_drafts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Denormalised snapshot so analytics survive FK nulling.
    company_name = Column(String(255), nullable=True)
    to_name = Column(String(255), nullable=True)
    to_email = Column(String(255), nullable=True)

    status = Column(
        String(20), nullable=False, default=CC_STATUS_SELECTED,
        server_default=CC_STATUS_SELECTED, index=True,
    )
    priority_rank = Column(Integer, nullable=True, index=True)
    quality_score = Column(Integer, nullable=True, index=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    rfq_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    campaign = relationship("Campaign", back_populates="contacts", lazy="selectin")
    company = relationship("CompanyLead", lazy="selectin")
    contact = relationship("Contact", lazy="selectin")
    draft = relationship("EmailDraft", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CampaignContact id={self.id} campaign_id={self.campaign_id} "
            f"status={self.status!r}>"
        )
