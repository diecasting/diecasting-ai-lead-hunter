"""DiscoverySchedule ORM model — Phase 5 Stage 3 recurring discovery runs.

A schedule repeats a keyword-driven discovery job on a ``frequency``
(daily / weekly / monthly). Every run creates a linked ``DiscoveryJob`` row
(execution history) and auto-qualifies discoveries that clear the thresholds.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoverySchedule(Base):
    """A recurring, keyword-driven discovery configuration."""

    __tablename__ = "discovery_schedules"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    frequency = Column(
        String(20), nullable=False, default="daily", server_default="daily"
    )  # daily | weekly | monthly
    enabled = Column(
        Boolean, nullable=False, default=True, server_default="1", index=True
    )

    # Auto-qualification thresholds (Phase 5 Stage 3).
    lead_score_threshold = Column(
        Integer, nullable=False, default=50, server_default="50"
    )
    confidence_threshold = Column(
        Integer, nullable=False, default=40, server_default="40"
    )

    last_run = Column(DateTime(timezone=True), nullable=True)
    next_run = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Every scheduled run produces a DiscoveryJob (execution history).
    jobs = relationship(
        "DiscoveryJob",
        backref="schedule",
        cascade="all, delete-orphan",
        order_by="DiscoveryJob.id.desc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiscoverySchedule id={self.id} keyword={self.keyword!r} enabled={self.enabled}>"
