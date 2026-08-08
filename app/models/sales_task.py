"""SalesTask ORM model (Phase 10 Reply Intelligence Sales Automation).

A :class:`SalesTask` is a follow-up action created automatically when a
customer reply is analysed — for example "prepare quotation", "re-engage after
out-of-office", "route to correct contact", or "review suspected spam". Tasks
are owned by a :class:`ReplyAnalysis` and, where resolvable, by a
:class:`Contact` / :class:`CompanyLead`, and are tracked through an
``open`` -> ``done`` / ``cancelled`` lifecycle by the sales team.

All foreign keys are ``SET NULL`` so deleting an underlying reply / contact /
company never orphans a task — the task keeps its descriptive fields (title,
priority, category, due date) for the sales team to act on.
"""
from datetime import datetime, timezone

from sqlalchemy import (
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
# Lifecycle states
# ---------------------------------------------------------------------------
TASK_STATUS_OPEN = "open"
TASK_STATUS_DONE = "done"
TASK_STATUS_CANCELLED = "cancelled"

TASK_STATUSES = (
    TASK_STATUS_OPEN,
    TASK_STATUS_DONE,
    TASK_STATUS_CANCELLED,
)

# ---------------------------------------------------------------------------
# Priority vocabulary (mirrors the CRM / campaign priority labels)
# ---------------------------------------------------------------------------
TASK_PRIORITY_HIGH = "high"
TASK_PRIORITY_MEDIUM = "medium"
TASK_PRIORITY_LOW = "low"

TASK_PRIORITIES = (
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_MEDIUM,
    TASK_PRIORITY_LOW,
)


class SalesTask(Base):
    """A follow-up action created from a classified customer reply."""

    __tablename__ = "sales_tasks"

    id = Column(Integer, primary_key=True, index=True)

    # Ownership (all nullable so history survives downstream deletions).
    reply_id = Column(
        Integer,
        ForeignKey("reply_analyses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(
        String(20), nullable=False, default=TASK_PRIORITY_MEDIUM,
        server_default="medium", index=True,
    )
    status = Column(
        String(20), nullable=False, default=TASK_STATUS_OPEN,
        server_default="open", index=True,
    )
    category = Column(String(60), nullable=True, index=True)
    due_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    reply = relationship("ReplyAnalysis", backref="sales_tasks", lazy="selectin")
    contact = relationship("Contact", backref="sales_tasks", lazy="selectin")
    company = relationship("CompanyLead", backref="sales_tasks", lazy="selectin")
    opportunity = relationship("Opportunity", backref="sales_tasks", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SalesTask id={self.id} status={self.status!r} "
            f"priority={self.priority!r}>"
        )
