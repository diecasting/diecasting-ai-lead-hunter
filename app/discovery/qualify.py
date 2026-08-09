"""Phase 5 Stage 3 — Discovery qualification rules + CRM lead creation.

``qualification_rules_pass`` decides whether a discovery is a high-value
industrial lead; ``discovery_to_lead`` turns a qualified discovery into a
``CompanyLead`` row (deduplicated by website / prior link). Both are shared
by the scheduled auto-qualification and the manual "Add to CRM" endpoint.
"""
import json
import logging
from typing import Callable, Optional, Tuple

from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.discovery import crud as discovery_crud
from app.models.company_discovery import CompanyDiscovery
from app.models.lead import CompanyLead

logger = logging.getLogger(__name__)


def qualification_rules_pass(
    discovery: CompanyDiscovery,
    *,
    lead_score_threshold: int = 50,
    confidence_threshold: int = 40,
) -> Tuple[bool, str]:
    """Apply the Phase 5 Stage 3 qualification rules.

    All must hold: lead_score >= threshold, confidence_score >= threshold,
    a manufacturing process was detected, and a buying signal exists.
    Returns ``(passed, reason)``; the reason is empty when passed.
    """
    if discovery.lead_score is None or discovery.lead_score < lead_score_threshold:
        return (
            False,
            f"lead_score {discovery.lead_score} below threshold {lead_score_threshold}",
        )
    if (
        discovery.confidence_score is None
        or discovery.confidence_score < confidence_threshold
    ):
        return (
            False,
            f"confidence {discovery.confidence_score} below threshold {confidence_threshold}",
        )
    if not (discovery.detected_processes or "").strip():
        return False, "no manufacturing process detected"
    if not (discovery.buying_signals or "").strip():
        return False, "no buying signal detected"
    return True, ""


def discovery_to_lead(
    db: Session,
    discovery: CompanyDiscovery,
    *,
    contact_discovery_fetcher: Optional[Callable[[str], object]] = None,
) -> Tuple[CompanyLead, str]:
    """Create (or return) the CRM lead for a discovery.

    Returns ``(lead, status)`` where status is one of:
      * ``created``          — a new lead was created and linked
      * ``already_linked``   — this discovery already produced a lead
      * ``duplicate_website``— another lead already owns the website

    After a new lead is created, Phase 13.2.1 enriches it with discovered
    contacts via the :class:`ContactDiscoveryService`. Contact discovery runs
    in a self-contained step: the lead is committed *first*, and any discovery
    failure is logged but never rolls back or blocks lead creation.

    No email is sent here — the Lead -> Outreach pipeline applies later.
    """
    if discovery.lead_id is not None:
        existing = leads_crud.get(db, discovery.lead_id)
        if existing is not None:
            return existing, "already_linked"

    website = discovery.website or None
    if website and leads_crud.get_by_website(db, website):
        existing = leads_crud.get_by_website(db, website)
        return existing, "duplicate_website"

    profile = {}
    if discovery.profile:
        try:
            profile = json.loads(discovery.profile)
        except Exception:
            profile = {}

    lead_score = discovery.lead_score or 0
    priority = "HIGH" if lead_score >= 70 else ("MEDIUM" if lead_score >= 50 else "LOW")

    lead = leads_crud.create(
        db,
        name=discovery.company_name,
        website=website,
        country=discovery.country,
        industry=discovery.industry,
        business_type=profile.get("business_type"),
        description=profile.get("description"),
        materials=", ".join(
            (discovery.detected_materials or "").split(", ")
        ) or None,
        manufacturing_process=", ".join(
            (discovery.detected_processes or "").split(", ")
        ) or None,
        buying_signal=discovery.buying_signals,
        contact_role=discovery.recommended_contact_role,
        lead_score=lead_score if lead_score else None,
        priority=priority,
        sales_priority=priority,
        lead_source="discovery",
        crawl_status="pending",
    )
    discovery_crud.link_to_lead(db, discovery, lead.id)
    # Commit the lead independently so a contact-discovery failure can never
    # undo the lead creation (requirement: lead creation is the source of truth).
    db.commit()

    # Phase 13.2.1: enrich the lead with discovered contacts. Isolated by design.
    _run_contact_discovery(db, lead, fetcher=contact_discovery_fetcher)

    return lead, "created"


def _run_contact_discovery(
    db: Session,
    lead: CompanyLead,
    *,
    fetcher: Optional[Callable[[str], object]] = None,
) -> None:
    """Run the Contact Discovery Engine for ``lead`` and log the outcome.

    Any exception is caught and logged; the function never raises, so callers
    (``discovery_to_lead``) can treat lead creation and contact discovery as
    fully independent steps.
    """
    try:
        from app.contact_discovery.service import ContactDiscoveryService

        service = ContactDiscoveryService()
        summary = service.discover_company_contacts(db, lead, fetcher=fetcher)
        logger.info(
            "contact_discovery_completed",
            extra={
                "lead_id": lead.id,
                "website": lead.website,
                "contacts_created": summary.get("total_contacts_created", 0),
                "summary": summary,
            },
        )
    except Exception:  # pragma: no cover - defensive boundary
        logger.error(
            "contact_discovery_failed",
            extra={"lead_id": lead.id, "website": lead.website},
            exc_info=True,
        )
