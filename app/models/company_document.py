"""CompanyDocument ORM model (Phase 2.3, section 4).

Stores text extracted from a lead's downloadable documents (catalogs,
brochures, PDF specs) so capability signals (machine capacity, tolerance,
materials, certifications, industries) can be mined and merged into the lead's
intelligence profile.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

from app.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class CompanyDocument(Base):
    __tablename__ = "company_documents"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("company_leads.id"), nullable=False, index=True
    )
    url = Column(String(1024), nullable=False)        # source URL of the document
    file_type = Column(String(20), nullable=True)     # e.g. "pdf"
    content = Column(Text, nullable=True)             # extracted plain text
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyDocument id={self.id} lead_id={self.lead_id} url={self.url!r}>"
