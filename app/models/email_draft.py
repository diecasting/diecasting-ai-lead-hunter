"""EmailDraft ORM model (Phase 9 AI Sales Agent).

Stores AI-generated, contact-personalised sales email *drafts* produced by the
AI Sales Agent. These are deliberately distinct from the Outreach Engine's
``outreach_messages`` table, which owns the actual send pipeline / engagement
tracking. Drafts here are the agent's working copies: they can be reviewed,
edited, scored and approved before being handed to the existing outreach
workflow for sending. Nothing in this model touches the send path, so the
outreach workflow is fully preserved.

Links:
  * company_id       -> company_leads.id       (CASCADE: drop drafts with company)
  * contact_id       -> contacts.id            (SET NULL: keep draft if contact gone)
  * email_address_id -> email_addresses.id     (SET NULL)
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
# Draft lifecycle states
# ---------------------------------------------------------------------------
DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_APPROVED = "approved"
DRAFT_STATUS_REJECTED = "rejected"
DRAFT_STATUS_QUEUED = "queued"

DRAFT_STATUSES = (
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_REJECTED,
    DRAFT_STATUS_QUEUED,
)


class EmailDraft(Base):
    """An AI-generated, editable sales email draft for a company / contact."""

    __tablename__ = "email_drafts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email_address_id = Column(
        Integer,
        ForeignKey("email_addresses.id", ondelete="SET NULL"),
        nullable=True,
    )

    to_name = Column(String(255), nullable=True)
    to_email = Column(String(255), nullable=True)

    subject = Column(Text, nullable=False, default="")
    opening = Column(Text, nullable=True)
    body = Column(Text, nullable=False, default="")
    call_to_action = Column(Text, nullable=True)

    status = Column(
        String(20),
        nullable=False,
        default=DRAFT_STATUS_DRAFT,
        server_default=DRAFT_STATUS_DRAFT,
        index=True,
    )

    # Which role / persona the agent wrote this for.
    role_category = Column(String(40), nullable=True, index=True)
    prompt_role = Column(String(40), nullable=True)

    # Scores computed at generation time.
    personalization_score = Column(Integer, nullable=True, index=True)
    quality_score = Column(Integer, nullable=True, index=True)

    # Optional structured company research snapshot (JSON text).
    research_summary = Column(Text, nullable=True)

    used_ai = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    company = relationship("CompanyLead", backref="email_drafts", lazy="selectin")
    contact = relationship("Contact", backref="email_drafts", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EmailDraft id={self.id} company_id={self.company_id} "
            f"status={self.status!r}>"
        )
