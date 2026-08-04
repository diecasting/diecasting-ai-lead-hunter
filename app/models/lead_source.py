"""LeadSource ORM model (Phase 3 Stage 1).

A ``LeadSource`` is a canonical acquisition channel (e.g. ``google_search``,
``linkedin``, ``trade_show``, ``referral``). ``CompanyLead.acquisition_channel``
references a source name so reporting can group leads by where they came from.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadSource(Base):
    """A canonical acquisition channel used to attribute leads."""

    __tablename__ = "lead_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    description = Column(String(512), nullable=True)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default="1", index=True
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LeadSource id={self.id} name={self.name!r}>"
