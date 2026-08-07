"""Company research summary generator (Phase 9 AI Sales Agent).

Aggregates everything we know about a prospect company into a structured,
sales-ready research brief:

  * company profile + AI fit scores (casting / cnc / tooling need, priority)
  * the buying signal
  * the best contacts (from Contact Intelligence, ranked by purchasing priority)
  * the best verified e-mails (from the Email Discovery engine)
  * a recommended outreach angle derived from the strongest contact's role

Deterministic by default. When ``use_ai`` is set and an LLM provider is
configured, the narrative ``ai_summary`` paragraph is enriched via the provider
abstraction; otherwise it is left empty and the deterministic ``fit_summary`` is
used by callers.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ai_sales_agent.llm import complete_json
from app.ai_sales_agent.prompts import role_cta, role_focus
from app.contact_intelligence.titles import classify_title_category


@dataclass
class CompanyResearch:
    company_id: int
    company: str
    industry: str = ""
    country: str = ""
    business_type: str = ""
    materials: str = ""
    manufacturing_process: str = ""
    products: str = ""
    buying_signal: str = ""
    ai_scores: Dict[str, Any] = field(default_factory=dict)
    fit_summary: str = ""
    recommended_angle: str = ""
    top_contacts: List[Dict[str, Any]] = field(default_factory=list)
    verified_emails: List[Dict[str, Any]] = field(default_factory=list)
    ai_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "company": self.company,
            "industry": self.industry,
            "country": self.country,
            "business_type": self.business_type,
            "materials": self.materials,
            "manufacturing_process": self.manufacturing_process,
            "products": self.products,
            "buying_signal": self.buying_signal,
            "ai_scores": self.ai_scores,
            "fit_summary": self.fit_summary,
            "recommended_angle": self.recommended_angle,
            "top_contacts": self.top_contacts,
            "verified_emails": self.verified_emails,
            "ai_summary": self.ai_summary,
        }


def _fit_summary(lead, scores: Dict[str, Any]) -> str:
    casting = scores.get("casting_need_score") or 0
    cnc = scores.get("cnc_need_score") or 0
    tooling = scores.get("tooling_need_score") or 0
    priority = (scores.get("sales_priority") or lead.sales_priority or "")
    name = lead.name or "This company"
    if str(priority).upper() == "HIGH":
        return (
            f"{name} shows a HIGH-fit die casting / CNC / tooling need "
            f"(casting {casting}, cnc {cnc}, tooling {tooling})."
        )
    if str(priority).upper() == "MEDIUM":
        return (
            f"{name} shows a MODERATE-fit need worth a targeted approach "
            f"(casting {casting}, cnc {cnc}, tooling {tooling})."
        )
    return (
        f"{name} shows a lower immediate need (casting {casting}, cnc {cnc}, "
        f"tooling {tooling}); nurture with capability content."
    )


def generate_research(
    lead,
    *,
    db=None,
    contacts=None,
    emails=None,
    use_ai: bool = False,
) -> CompanyResearch:
    """Build a structured research brief for ``lead`` (a ``CompanyLead``).

    ``contacts`` / ``emails`` may be pre-fetched lists (used when we already
    have them, e.g. from the draft service); otherwise they are loaded from the
    DB when a session is supplied.
    """
    scores = {
        "casting_need_score": getattr(lead, "casting_need_score", None) or 0,
        "cnc_need_score": getattr(lead, "cnc_need_score", None) or 0,
        "tooling_need_score": getattr(lead, "tooling_need_score", None) or 0,
        "sales_priority": getattr(lead, "sales_priority", "") or "",
        "ai_score": getattr(lead, "ai_score", None),
        "ai_relevant": getattr(lead, "ai_relevant", None),
    }

    if contacts is None and db is not None:
        try:
            from app.contact_intelligence.crud import list_for_company

            contacts = list_for_company(db, lead.id)
        except Exception:
            contacts = []
    if emails is None and db is not None:
        try:
            from app.email_discovery.crud import list_by_company

            emails = list_by_company(db, lead.id)
        except Exception:
            emails = []

    top_contacts: List[Dict[str, Any]] = []
    best_category = ""
    if contacts:
        def _pscore(c) -> int:
            return getattr(c, "purchasing_score", None) or 0

        for c in sorted(contacts, key=_pscore, reverse=True)[:5]:
            cat = getattr(c, "title_category", None) or ""
            if not cat:
                cat = classify_title_category(getattr(c, "title", None) or "")
            if not best_category and cat:
                best_category = cat
            top_contacts.append(
                {
                    "id": c.id,
                    "name": getattr(c, "full_name", None) or "",
                    "title": getattr(c, "title", None)
                    or getattr(c, "role", None)
                    or "",
                    "title_category": cat,
                    "priority": getattr(c, "priority", "") or "",
                    "purchasing_score": _pscore(c),
                    "email": getattr(c, "email", None) or "",
                }
            )

    verified_emails: List[Dict[str, Any]] = []
    if emails:
        for e in emails:
            status = getattr(e, "verification_status", "") or ""
            if status in ("valid", "risky"):
                verified_emails.append(
                    {
                        "id": e.id,
                        "email": getattr(e, "email", ""),
                        "email_type": getattr(e, "email_type", "") or "",
                        "verification_status": status,
                        "verification_score": getattr(e, "verification_score", None),
                    }
                )

    recommended_angle = ""
    if best_category:
        recommended_angle = (
            f"Lead with {role_focus(best_category)}; {role_cta(best_category)}."
        )

    research = CompanyResearch(
        company_id=lead.id,
        company=lead.name or "",
        industry=lead.industry or "",
        country=lead.country or "",
        business_type=lead.business_type or "",
        materials=lead.materials or "",
        manufacturing_process=lead.manufacturing_process or "",
        products=lead.description or "",
        buying_signal=lead.buying_signal or "",
        ai_scores=scores,
        fit_summary=_fit_summary(lead, scores),
        recommended_angle=recommended_angle,
        top_contacts=top_contacts,
        verified_emails=verified_emails,
    )

    if use_ai:
        ai_summary = _ai_summary(research)
        if ai_summary:
            research.ai_summary = ai_summary

    return research


def _ai_summary(research: CompanyResearch) -> str:
    system = (
        "You are a B2B sales-intelligence analyst for the metal die-casting "
        "industry. Write one concise paragraph (English) explaining why this "
        "company is a good fit for precision die casting / CNC / tooling "
        "services, referencing its industry, materials and best contact."
    )
    user = json.dumps(research.to_dict(), ensure_ascii=False, indent=2)
    data = complete_json(system, user, temperature=0.2)
    if data:
        return str(data.get("summary") or data.get("ai_summary") or "").strip()
    return ""
