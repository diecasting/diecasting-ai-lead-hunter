"""DiscoveryJob + DiscoveryTask ORM models — Phase 5 Stage 2 batch queue.

A :class:`DiscoveryJob` batches keyword-driven prospect discovery: it resolves
candidate URLs from a search keyword and tracks overall progress. Each URL
becomes a :class:`DiscoveryTask`; the job's ``run`` processes them through the
website-analysis pipeline, linking successful analyses to ``CompanyDiscovery``
rows so the operator can bulk-add them to the CRM.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoveryJob(Base):
    """A batch discovery run driven by one search keyword."""

    __tablename__ = "discovery_jobs"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    schedule_id = Column(
        Integer,
        ForeignKey("discovery_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        String(20), nullable=False, default="pending",
        server_default="pending", index=True,
    )  # pending | running | completed | failed
    total_urls = Column(Integer, nullable=False, default=0, server_default="0")
    processed_urls = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    tasks = relationship(
        "DiscoveryTask",
        backref="job",
        cascade="all, delete-orphan",
        order_by="DiscoveryTask.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiscoveryJob id={self.id} keyword={self.keyword!r} status={self.status!r}>"


class DiscoveryTask(Base):
    """A single URL to analyse within a discovery job."""

    __tablename__ = "discovery_tasks"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        Integer,
        ForeignKey("discovery_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = Column(String(512), nullable=False, index=True)
    status = Column(
        String(20), nullable=False, default="pending",
        server_default="pending", index=True,
    )  # pending | analyzed | failed | skipped
    discovery_id = Column(
        Integer,
        ForeignKey("company_discoveries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    discovery = relationship("CompanyDiscovery", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiscoveryTask id={self.id} url={self.url!r} status={self.status!r}>"
