"""CompanyDiscovery ORM model — Phase 5 Stage 1 lead discovery records.

Stores the outcome of analysing a prospect's website: the extracted industrial
profile (materials, processes, buying signals), the provenance of the
discovery (``discovery_source``), a 0-100 ``confidence_score``, and — once the
operator adds it to the CRM — a link to the resulting ``CompanyLead`` row.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyDiscovery(Base):
    """A website analysis result for a discovered industrial prospect."""

    __tablename__ = "company_discoveries"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False, index=True)
    website = Column(String(512), nullable=True, index=True)
    country = Column(String(120), nullable=True)
    industry = Column(String(160), nullable=True)

    # Phase 5 Stage 1 extracted signals (comma-joined lists).
    detected_materials = Column(Text, nullable=True)
    detected_processes = Column(Text, nullable=True)
    buying_signals = Column(Text, nullable=True)

    # Provenance + quality.
    discovery_source = Column(
        String(120), nullable=False, default="url_analysis",
        server_default="url_analysis", index=True,
    )
    confidence_score = Column(Integer, nullable=True)  # 0-100

    # Denormalised analysis summary (lead score + recommended role).
    lead_score = Column(Integer, nullable=True)  # 0-100
    recommended_contact_role = Column(String(120), nullable=True)

    # Full profile JSON (description, products, industries served, supplier
    # opportunities, procurement breakdown) for the preview / re-analysis.
    profile = Column(Text, nullable=True)

    # Link to the CRM lead once the operator adds the discovery to the pipeline.
    lead_id = Column(
        Integer, ForeignKey("company_leads.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    lead = relationship("CompanyLead", backref="discoveries", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyDiscovery id={self.id} company={self.company_name!r} score={self.confidence_score}>"
