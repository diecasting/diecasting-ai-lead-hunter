"""Phase 5 Stage 1 — AI Lead Discovery website-analysis pipeline.

``analyze_website(url)`` crawls a prospect's site and produces a
:class:`DiscoveryResult`: the industrial profile (description, products,
industries served, materials, manufacturing processes, buying signals,
supplier opportunities) plus a deterministic 0-100 ``lead_score``, a
``confidence_score``, and the recommended primary contact role.

The pipeline reuses the existing rule-based intelligence stack
(``app.ai.scoring.build_analysis`` + ``app.ai.procurement_signals`` +
``app.outreach.contact_role_detector``) so no LLM key is required and the
behaviour is fully deterministic / testable offline. The crawler is
injectable so tests never touch the network.

This stage deliberately does NOT send emails — a discovered prospect is only
added to the CRM (``POST /discovery/{id}/lead``), after which the existing
Lead → Outreach pipeline takes over.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.ai.procurement_signals import analyze_procurement_signals
from app.ai.scoring import (
    build_analysis,
    business_type,
    detect_buying_signal,
    detect_industries,
    detect_materials,
    detect_processes,
    detect_products,
)
from app.outreach.contact_role_detector import detect_primary_role

# Procurement components that signal a supplier opportunity worth flagging.
_OPPORTUNITY_COMPONENTS = (
    "casting",
    "cnc",
    "oem",
    "supplier",
    "manufacturing_capability",
)


@dataclass
class DiscoveryResult:
    """Structured outcome of a website analysis (preview + persistence)."""

    url: str
    company_name: str = ""
    country: str = ""
    industry: str = ""
    business_type: str = ""
    description: str = ""
    products: List[str] = field(default_factory=list)
    industries_served: List[str] = field(default_factory=list)
    detected_materials: List[str] = field(default_factory=list)
    detected_processes: List[str] = field(default_factory=list)
    buying_signals: List[str] = field(default_factory=list)
    supplier_opportunities: List[str] = field(default_factory=list)
    discovery_source: str = "url_analysis"
    confidence_score: int = 0
    lead_score: int = 0
    recommended_contact_role: str = ""
    procurement_type: str = ""
    procurement_score: int = 0

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "company_name": self.company_name,
            "country": self.country,
            "industry": self.industry,
            "business_type": self.business_type,
            "description": self.description,
            "products": self.products,
            "industries_served": self.industries_served,
            "detected_materials": self.detected_materials,
            "detected_processes": self.detected_processes,
            "buying_signals": self.buying_signals,
            "supplier_opportunities": self.supplier_opportunities,
            "discovery_source": self.discovery_source,
            "confidence_score": self.confidence_score,
            "lead_score": self.lead_score,
            "recommended_contact_role": self.recommended_contact_role,
            "procurement_type": self.procurement_type,
            "procurement_score": self.procurement_score,
        }

    def to_profile_json(self) -> str:
        """JSON blob persisted on the discovery row for later re-preview."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _domain_from_url(url: str) -> str:
    m = re.search(r"https?://([^/]+)", (url or "").strip())
    return m.group(1) if m else (url or "").strip()


def derive_company_name(url: str) -> str:
    """Best-effort company name from the URL host (acme-casting.com -> Acme Casting)."""
    if not (url or "").strip():
        return ""
    domain = _domain_from_url(url)
    if not domain:
        return url or "Unknown company"
    labels = [label for label in domain.split(":")[0].split(".") if label and label != "www"]
    if not labels:
        return domain
    name = re.sub(r"[-_]+", " ", labels[0]).strip()
    return name.title() if name else domain


def _confidence_score(text: str, procurement: Dict) -> int:
    """0-100: how much usable signal text the crawl produced."""
    score = 40
    score += min(30, len(text or "") // 300)
    matched = sum(
        len(comp.get("matched") or [])
        for comp in procurement.get("components", {}).values()
    )
    score += min(30, matched * 6)
    return min(100, max(0, score))


def compute_lead_score(
    *, procurement_score: int, materials: List[str], processes: List[str],
    buying_signals: List[str],
) -> int:
    """Deterministic 0-100 qualification score for a discovery.

    Weights: procurement intent 55%, material/process richness 25%, buying
    signal intensity 20% — mirroring the CRM lead-scoring philosophy without
    needing a persisted ``CompanyLead`` row.
    """
    richness = min(100, len(materials or []) * 15 + len(processes or []) * 15)
    signal_score = min(100, len(buying_signals or []) * 20)
    score = 0.55 * int(procurement_score) + 0.25 * richness + 0.20 * signal_score
    return int(round(score))


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def analyze_website(url: str, *, crawler=None, use_llm: bool = False) -> DiscoveryResult:
    """Crawl ``url`` and produce the qualification-ready discovery profile.

    ``crawler`` is injectable for tests: any object with ``crawl(url)`` whose
    result exposes ``text_content`` (or ``text``). No database writes happen
    here — persistence is the caller's job.
    """
    url = (url or "").strip()
    if crawler is None:
        from app.crawler.website_crawler import WebsiteCrawler

        crawler = WebsiteCrawler()
    result = crawler.crawl(url)
    text = getattr(result, "text_content", None) or getattr(result, "text", "") or ""

    # 1) Rule-based industrial intelligence (reuses the Phase 2.3 stack).
    analysis = build_analysis(text=text, company="", country="", industry="")
    procurement = analyze_procurement_signals(text)

    materials = detect_materials(text)
    processes = detect_processes(text)
    industries = detect_industries(text)
    products = detect_products(text)

    # 2) Buying signals: procurement match phrases + detected signal level.
    buying_signals: List[str] = []
    for comp in procurement.get("components", {}).values():
        for phrase in comp.get("matched") or []:
            if phrase not in buying_signals:
                buying_signals.append(phrase)
    signal = detect_buying_signal(text)
    if signal.get("level") and signal["level"] not in ("LOW", "MEDIUM", "HIGH"):
        buying_signals.append(str(signal["level"]))
    elif signal.get("detail"):
        buying_signals.append(str(signal["detail"]))
    buying_signals = buying_signals[:12]

    # 3) Supplier opportunities: procurement components above the threshold.
    supplier_opportunities: List[str] = []
    for ctype in _OPPORTUNITY_COMPONENTS:
        comp = procurement.get("components", {}).get(ctype, {})
        if comp.get("score", 0) >= 40:
            label = ctype.replace("_", " ").title()
            supplier_opportunities.append(
                f"{label} supply opportunity (score {comp['score']})"
            )

    company_name = derive_company_name(url)
    industry = ", ".join(industries[:2]) if industries else (
        analysis.get("industry") or "Die casting / Precision manufacturing"
    )
    proc_score = int(procurement.get("procurement_score") or 0)
    lead_score = compute_lead_score(
        procurement_score=proc_score,
        materials=materials,
        processes=processes,
        buying_signals=buying_signals,
    )
    role = detect_primary_role(
        industry=industry,
        business_type=analysis.get("business_type") or "",
        buying_signal=analysis.get("buying_signal") or "",
    )

    return DiscoveryResult(
        url=url,
        company_name=company_name,
        country=analysis.get("country") or "",
        industry=industry,
        business_type=analysis.get("business_type") or "",
        description=analysis.get("reason") or text[:400] or "",
        products=products or [],
        industries_served=industries or [],
        detected_materials=materials or [],
        detected_processes=processes or [],
        buying_signals=buying_signals,
        supplier_opportunities=supplier_opportunities,
        discovery_source="url_analysis",
        confidence_score=_confidence_score(text, procurement),
        lead_score=lead_score,
        recommended_contact_role=role,
        procurement_type=procurement.get("procurement_type") or "",
        procurement_score=proc_score,
    )
