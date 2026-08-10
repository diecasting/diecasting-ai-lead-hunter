"""Personalization context builder (Phase 14.2).

Turns a :class:`~app.models.lead.CompanyLead` + :class:`~app.models.contact.Contact`
pair (plus our own manufacturing capabilities) into a flat, serialisable
:class:`PersonalizationContext` that the prompt generator can render without any
branching on ORM types.

Design constraints (per Phase 14.2 scope):
  * deterministic — no LLM, no network, no external APIs
  * pure / offline — does NOT touch the database (the service layer loads the
    capability rows and passes them in as plain objects or dicts)
  * does NOT modify any sending / gate / schema
"""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Union


@dataclass
class PersonalizationContext:
    """Flat, render-ready snapshot of a (company, contact) pairing."""

    # --- Company (prospect) side -------------------------------------------
    company_id: Optional[int]
    company_name: str
    company_industry: Optional[str]
    company_country: Optional[str]
    company_description: Optional[str]
    company_materials: List[str]
    company_processes: List[str]
    company_casting_need_score: Optional[int]
    company_cnc_need_score: Optional[int]
    company_tooling_need_score: Optional[int]
    company_sales_priority: Optional[str]
    company_business_type: Optional[str]
    company_website: Optional[str]

    # --- Contact (recipient) side ------------------------------------------
    contact_id: Optional[int]
    contact_name: str
    contact_role: Optional[str]
    contact_title: Optional[str]
    contact_title_category: Optional[str]
    contact_seniority: Optional[str]
    contact_email: Optional[str]
    ranking_score: Optional[int]
    ranking_confidence: Optional[str]
    ranking_reason: Optional[str]

    # --- Our own manufacturing base (matched against the prospect) ---------
    capabilities: List[dict] = field(default_factory=list)
    capability_match: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split_csv(text: Optional[str]) -> List[str]:
    """Split a comma-separated field into a clean list (empty-safe)."""
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part and part.strip()]


def _cap_summary(cap: Union[object, dict]) -> str:
    """Render a capability row (ORM object or dict) to a short summary string."""
    if isinstance(cap, dict):
        get = cap.get
    else:
        get = lambda k, default=None: getattr(cap, k, default)  # noqa: E731

    process = get("process")
    tonnage = get("tonnage")
    materials = _split_csv(get("material_compatibility"))
    tolerance = get("tolerance_capability")

    parts = []
    if process:
        parts.append(str(process))
    if tonnage:
        parts.append(f"{tonnage}T")
    if materials:
        parts.append("(" + ",".join(materials) + ")")
    if tolerance:
        parts.append(tolerance)
    return " ".join(parts) if parts else "general capability"


def _cap_materials(cap: Union[object, dict]) -> List[str]:
    if isinstance(cap, dict):
        raw = cap.get("material_compatibility")
    else:
        raw = getattr(cap, "material_compatibility", None)
    return _split_csv(raw)


def _cap_process(cap: Union[object, dict]) -> Optional[str]:
    if isinstance(cap, dict):
        return cap.get("process")
    return getattr(cap, "process", None)


def _match_capabilities(
    capabilities: Sequence[Union[object, dict]],
    company_materials: List[str],
    company_processes: List[str],
) -> List[str]:
    """Return summaries of capabilities that overlap the prospect's needs."""
    material_set = {m.lower() for m in company_materials}
    process_set = {p.lower() for p in company_processes}
    matched: List[str] = []
    for cap in capabilities or []:
        cap_materials = {m.lower() for m in _cap_materials(cap)}
        cap_process = (_cap_process(cap) or "").lower()
        if material_set & cap_materials or (process_set and cap_process in process_set):
            matched.append(_cap_summary(cap))
    return matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_personalization_context(
    company,
    contact,
    capabilities: Optional[Sequence[Union[object, dict]]] = None,
) -> PersonalizationContext:
    """Build a :class:`PersonalizationContext` from a company + contact.

    ``capabilities`` is our own manufacturing base (list of
    :class:`~app.models.manufacturing_capability.ManufacturingCapability`
    objects or plain dicts). When omitted, no capability matching is performed.

    All attribute access is guarded so partially-populated / ``None`` records
    degrade gracefully instead of raising.
    """
    company_id = getattr(company, "id", None)
    company_name = (getattr(company, "name", None) or "your company").strip()
    company_industry = getattr(company, "industry", None)
    company_country = getattr(company, "country", None)
    company_description = getattr(company, "description", None)
    company_materials = _split_csv(getattr(company, "materials", None))
    company_processes = _split_csv(getattr(company, "manufacturing_process", None))
    company_casting_need_score = getattr(company, "casting_need_score", None)
    company_cnc_need_score = getattr(company, "cnc_need_score", None)
    company_tooling_need_score = getattr(company, "tooling_need_score", None)
    company_sales_priority = getattr(company, "sales_priority", None)
    company_business_type = getattr(company, "business_type", None)
    company_website = getattr(company, "website", None)

    contact_id = getattr(contact, "id", None)
    full_name = (
        getattr(contact, "full_name", None)
        or _join_name(contact)
        or ""
    )
    contact_role = getattr(contact, "role", None)
    contact_title = getattr(contact, "title", None)
    contact_title_category = getattr(contact, "title_category", None)
    contact_seniority = getattr(contact, "seniority", None)
    contact_email = getattr(contact, "email", None)
    ranking_score = getattr(contact, "ranking_score", None)
    ranking_confidence = getattr(contact, "ranking_confidence", None)
    ranking_reason = getattr(contact, "ranking_reason", None)

    caps_as_dicts: List[dict] = []
    for cap in capabilities or []:
        caps_as_dicts.append(_cap_to_dict(cap))
    capability_match = _match_capabilities(
        caps_as_dicts, company_materials, company_processes
    )

    return PersonalizationContext(
        company_id=company_id,
        company_name=company_name,
        company_industry=company_industry,
        company_country=company_country,
        company_description=company_description,
        company_materials=company_materials,
        company_processes=company_processes,
        company_casting_need_score=company_casting_need_score,
        company_cnc_need_score=company_cnc_need_score,
        company_tooling_need_score=company_tooling_need_score,
        company_sales_priority=company_sales_priority,
        company_business_type=company_business_type,
        company_website=company_website,
        contact_id=contact_id,
        contact_name=full_name,
        contact_role=contact_role,
        contact_title=contact_title,
        contact_title_category=contact_title_category,
        contact_seniority=contact_seniority,
        contact_email=contact_email,
        ranking_score=ranking_score,
        ranking_confidence=ranking_confidence,
        ranking_reason=ranking_reason,
        capabilities=caps_as_dicts,
        capability_match=capability_match,
    )


def _join_name(contact) -> Optional[str]:
    first = getattr(contact, "first_name", None)
    last = getattr(contact, "last_name", None)
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else None


def _cap_to_dict(cap: Union[object, dict]) -> dict:
    if isinstance(cap, dict):
        return dict(cap)
    return {
        "process": getattr(cap, "process", None),
        "machine_type": getattr(cap, "machine_type", None),
        "tonnage": getattr(cap, "tonnage", None),
        "material_compatibility": getattr(cap, "material_compatibility", None),
        "max_part_weight": getattr(cap, "max_part_weight", None),
        "tolerance_capability": getattr(cap, "tolerance_capability", None),
        "active": getattr(cap, "active", True),
    }
