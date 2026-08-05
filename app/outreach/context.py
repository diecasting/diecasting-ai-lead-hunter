"""Customer context aggregation (Phase 4 Stage 2).

Collects every signal we hold about a prospect into a single
:class:`CustomerContext` object so the personalization engine (email generator
+ quality scorer) has one consistent input instead of a sprawl of loose fields.

Inputs aggregated:
  * company profile   — name, industry, country, business_type, products,
                        materials, manufacturing_process, description
  * procurement signals — casting / CNC / OEM / supplier / manufacturing
                        capability scores + dominant type (from Stage 2)
  * PDF intelligence  — capability / catalog / technical document signals
  * contact role      — the selected recipient's role/title
  * lead score        — composite 0–100 + priority (from Stage 3)

The context is intentionally plain-data (dataclass) so it can be built from a
``CompanyLead`` ORM row, from raw dicts (tests/fixtures), or assembled piece by
piece. ``build_context_from_lead`` reads a ``CompanyLead`` directly.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.ai.lead_scoring import score_lead
from app.ai.procurement_signals import analyze_procurement_signals
from app.outreach.contact_role_detector import detect_primary_role


@dataclass
class CustomerContext:
    """Aggregated, personalization-ready view of a single prospect."""

    # --- Company profile --------------------------------------------------
    company: str = ""
    industry: str = ""
    country: str = ""
    business_type: str = ""
    products: str = ""
    materials: str = ""
    manufacturing_process: str = ""
    description: str = ""

    # --- Procurement signals (Stage 2) ------------------------------------
    procurement_signals: Dict[str, object] = field(default_factory=dict)
    procurement_score: int = 0
    procurement_type: str = ""

    # --- PDF intelligence (Stage 2) --------------------------------------
    pdf_types: List[str] = field(default_factory=list)
    pdf_intelligence: str = ""

    # --- Contact / role ---------------------------------------------------
    contact_role: str = ""
    contact_name: str = ""

    # --- Lead score (Stage 3) --------------------------------------------
    lead_score: Optional[int] = None
    priority: str = ""

    # --- Raw buying signal (for messaging intensity) --------------------
    buying_signal: str = ""

    def merged_text(self) -> str:
        """Concatenate the textual signals for scoring / keyword detection."""
        return " ".join(
            p for p in [
                self.description, self.products, self.materials,
                self.manufacturing_process, self.pdf_intelligence,
            ] if p
        )


def _extract_procurement(lead) -> Dict[str, object]:
    """Pull procurement signals from a lead's ai_signals JSON, or recompute."""
    raw = getattr(lead, "ai_signals", None)
    if raw:
        try:
            import json

            data = json.loads(raw)
            proc = data.get("procurement_signals")
            if proc:
                return proc
        except Exception:
            pass
    # Fall back to recomputing from website content / description.
    text = getattr(lead, "website_content", None) or getattr(lead, "description", "") or ""
    try:
        return analyze_procurement_signals(text or "")
    except Exception:
        return {}


def build_context_from_lead(lead, *, db=None) -> CustomerContext:
    """Build a :class:`CustomerContext` from a ``CompanyLead`` ORM row.

    When ``db`` is supplied, the composite ``lead_score`` is recomputed (it also
    reads related contacts / documents); otherwise the stored ``lead_score`` /
    ``priority`` columns are used as-is.
    """
    procurement = _extract_procurement(lead)
    proc_score = int(procurement.get("score") or 0)
    proc_type = str(procurement.get("type") or "")

    # PDF intelligence: scan related company_documents for capability signals.
    pdf_types: List[str] = []
    pdf_intel_text = ""
    if db is not None:
        try:
            from app.crud import company_documents as doc_crud

            docs = doc_crud.get_by_lead(db, lead.id)
            for d in docs:
                ftype = (getattr(d, "file_type", None) or "").lower()
                if ftype:
                    pdf_types.append(ftype)
                content = getattr(d, "content", None) or ""
                if content:
                    pdf_intel_text += " " + content[:2000]
        except Exception:
            pass

    # Prefer an explicitly stored contact role (set via the dashboard lead form);
    # otherwise fall back to keyword-based detection from the lead's signals.
    stored_role = getattr(lead, "contact_role", None) or ""
    role = stored_role or detect_primary_role(
        industry=lead.industry or "",
        business_type=lead.business_type or "",
        buying_signal=lead.buying_signal or "",
    )

    if db is not None:
        scored = score_lead(lead, db=db)
        lead_score = scored["lead_score"]
        priority = scored["priority"]
    else:
        lead_score = getattr(lead, "lead_score", None)
        priority = getattr(lead, "priority", "") or ""

    return CustomerContext(
        company=lead.name or "",
        industry=lead.industry or "",
        country=lead.country or "",
        business_type=lead.business_type or "",
        products=lead.description or "",
        materials=lead.materials or "",
        manufacturing_process=lead.manufacturing_process or "",
        description=lead.description or "",
        procurement_signals=procurement,
        procurement_score=proc_score,
        procurement_type=proc_type,
        pdf_types=pdf_types,
        pdf_intelligence=pdf_intel_text.strip(),
        contact_role=role,
        buying_signal=lead.buying_signal or "",
        lead_score=lead_score,
        priority=priority or "",
    )


def build_context(
    *,
    company: str = "",
    industry: str = "",
    country: str = "",
    business_type: str = "",
    products: str = "",
    materials: str = "",
    manufacturing_process: str = "",
    description: str = "",
    procurement_signals: Optional[Dict] = None,
    pdf_types: Optional[List[str]] = None,
    pdf_intelligence: str = "",
    contact_role: str = "",
    contact_name: str = "",
    lead_score: Optional[int] = None,
    priority: str = "",
    buying_signal: str = "",
) -> CustomerContext:
    """Construct a context from explicit keyword arguments (tests / fixtures)."""
    proc = procurement_signals or {}
    return CustomerContext(
        company=company,
        industry=industry,
        country=country,
        business_type=business_type,
        products=products,
        materials=materials,
        manufacturing_process=manufacturing_process,
        description=description,
        procurement_signals=proc,
        procurement_score=int(proc.get("score") or 0),
        procurement_type=str(proc.get("type") or ""),
        pdf_types=pdf_types or [],
        pdf_intelligence=pdf_intelligence,
        contact_role=contact_role,
        contact_name=contact_name,
        lead_score=lead_score,
        priority=priority,
        buying_signal=buying_signal,
    )
