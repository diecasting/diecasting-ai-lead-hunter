"""AI Lead Scoring & Prioritization Engine (Phase 3 Stage 3).

Combines the Phase 2.3 / 3.2 intelligence signals into a single composite
``lead_score`` (0–100) and a ``priority`` label (HIGH / MEDIUM / LOW).

Five weighted component scores feed the composite:

    company_fit_score      (weight 0.30) — core die-casting / CNC / tooling
                                            demand + business-type fit.
    procurement_signal_score (weight 0.20) — active buying / supplier posture.
    website_intent_score    (weight 0.20) — explicit buying-signal level on the
                                            website + procurement appetite.
    contact_quality_score   (weight 0.15) — number / role / reachability of
                                            extracted contacts.
    pdf_signal_score        (weight 0.15) — capability / catalog / technical
                                            documents the company publishes.

The engine is deterministic and transparent (no LLM) so scores are cheap,
reproducible, and fully explainable via ``lead_score_breakdown``.
"""
import json
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.ranking import HIGH, LOW, MEDIUM, primary_score
from app.ai.scoring import MEDIUM_THRESHOLD
from app.crud import company_documents as doc_crud
from app.crud import contacts as contacts_crud
from app.models.lead import CompanyLead

# ---------------------------------------------------------------------------
# Weights — must sum to 1.0. Tunable per business strategy.
# ---------------------------------------------------------------------------
W_COMPANY_FIT = 0.30
W_PROCUREMENT = 0.20
W_WEBSITE_INTENT = 0.20
W_CONTACT_QUALITY = 0.15
W_PDF_SIGNAL = 0.15

# Priority thresholds (composite lead_score).
PRIORITY_HIGH_THRESHOLD = 80
PRIORITY_MEDIUM_THRESHOLD = 50  # >=50 and <80 -> MEDIUM; <50 -> LOW

# Business-type fit bonus (added to company_fit_score, capped).
_BUSINESS_TYPE_FIT = {
    "Manufacturer / OEM": 25,
    "Supplier": 15,
    "Trader / Distributor": 5,
    "Unknown": 0,
}

# PDF document type -> signal contribution.
_PDF_TYPE_SIGNAL = {
    "capability": 40,
    "catalog": 20,
    "technical": 20,
}


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(value))))


def score_to_priority(score: int) -> str:
    """Map a composite lead_score to a priority label."""
    if score > PRIORITY_HIGH_THRESHOLD:
        return HIGH
    if score >= PRIORITY_MEDIUM_THRESHOLD:
        return MEDIUM
    return LOW


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------
def company_fit_score(
    *,
    casting_need_score: int = 0,
    cnc_need_score: int = 0,
    tooling_need_score: int = 0,
    business_type: str = "",
) -> int:
    """Core demand fit: strongest process need + business-type bonus.

    Uses ``ranking.primary_score`` (max of the three) as the base demand signal,
    then adds a business-type bonus (manufacturers/OEMs are the best fit).
    """
    base = primary_score(
        casting_need_score=casting_need_score,
        cnc_need_score=cnc_need_score,
        tooling_need_score=tooling_need_score,
    )
    bonus = _BUSINESS_TYPE_FIT.get(business_type or "Unknown", 0)
    return _clamp(base + bonus)


def procurement_signal_score(ai_signals: Optional[str] = None) -> int:
    """Read the Phase 3 Stage 2 procurement report (stored in ai_signals JSON).

    Returns the overall ``procurement_score`` (0–100), or 0 when absent.
    """
    if not ai_signals:
        return 0
    try:
        data = json.loads(ai_signals)
    except Exception:
        return 0
    procurement = data.get("procurement_signals") or {}
    score = procurement.get("score")
    if score is None:
        return 0
    return _clamp(int(score))


def website_intent_score(
    *,
    buying_signal: Optional[str] = None,
    ai_signals: Optional[str] = None,
) -> int:
    """Website buying intent: explicit buying-signal level + procurement appetite.

    The ``buying_signal`` column stores "<LEVEL> (detail)" or "<LEVEL>".
    HIGH=100, MEDIUM=65, LOW=35, NONE/empty=10. A live procurement score present
    in ``ai_signals`` lifts the floor so intent is never understated.
    """
    level = (buying_signal or "").split(" ")[0].strip().upper()
    level_map = {"HIGH": 100, "MEDIUM": 65, "LOW": 35}
    intent = level_map.get(level, 10)

    # Blend in procurement appetite if the website shows active buying posture.
    proc = procurement_signal_score(ai_signals)
    if proc > 0:
        # Use the stronger of the two intent signals (capped).
        intent = max(intent, min(100, int(proc * 0.9)))
    return _clamp(intent)


def contact_quality_score(contacts: List) -> int:
    """Quality of extracted contacts.

    Factors (each capped, summed then clamped 0–100):
      * coverage: up to 30 for having >=3 contacts
      * email:    up to 30 for having >=3 contacts with e-mails
      * role:     up to 25 for a buyer / purchasing / engineering role present
      * primary:  up to 10 for a marked primary contact
      * linkedin: up to 5 for any LinkedIn presence (only when role/email set)
    """
    if not contacts:
        return 0

    n = len(contacts)
    with_email = sum(1 for c in contacts if getattr(c, "email", None))
    with_role = sum(
        1
        for c in contacts
        if (getattr(c, "role", None) or getattr(c, "title", None))
    )
    has_primary = any(getattr(c, "is_primary", False) for c in contacts)

    coverage = min(30, n * 10)               # 1->10, 2->20, 3+->30
    email = min(30, with_email * 10)         # 1->10 ... 3+->30
    role = 0
    if with_role:
        role = 15 + min(10, (with_role - 1) * 5)  # 15..25
    primary = 10 if has_primary else 0
    linkedin = 5 if (with_email or with_role) else 0

    return _clamp(coverage + email + role + primary + linkedin)


def pdf_signal_score(documents: List) -> int:
    """Signal from published documents (capability > catalog/technical).

    A capability PDF is the strongest proof the company makes / sources
    die-cast parts; catalogs and technical docs add moderate signal.
    """
    if not documents:
        return 0
    total = 0
    seen = set()
    for doc in documents:
        ftype = (getattr(doc, "file_type", None) or "").lower()
        # file_type may be "pdf" with a sub-type elsewhere; look at the URL too.
        url = (getattr(doc, "url", None) or "").lower()
        signal = 0
        for key, value in _PDF_TYPE_SIGNAL.items():
            if key in ftype or key in url:
                signal = max(signal, value)
        # Default: any PDF document contributes a small baseline.
        if signal == 0:
            signal = 10
        total += signal
    return _clamp(total)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------
def compute_lead_score(
    *,
    company_fit: int = 0,
    procurement_signal: int = 0,
    website_intent: int = 0,
    contact_quality: int = 0,
    pdf_signal: int = 0,
) -> int:
    """Weighted composite, clamped to 0–100."""
    composite = (
        company_fit * W_COMPANY_FIT
        + procurement_signal * W_PROCUREMENT
        + website_intent * W_WEBSITE_INTENT
        + contact_quality * W_CONTACT_QUALITY
        + pdf_signal * W_PDF_SIGNAL
    )
    return _clamp(composite)


def score_lead(
    lead: CompanyLead,
    *,
    db: Optional[Session] = None,
) -> Dict:
    """Compute the full scoring payload for a ``CompanyLead``.

    Inputs: the lead ORM row (need scores, business_type, buying_signal,
    ai_signals) plus, when ``db`` is supplied, its related contacts and PDF
    documents. Returns a dict with the five component scores, the composite
    ``lead_score`` (0–100), the ``priority`` label, and an explainable
    ``breakdown`` dict.
    """
    company_fit = company_fit_score(
        casting_need_score=lead.casting_need_score or 0,
        cnc_need_score=lead.cnc_need_score or 0,
        tooling_need_score=lead.tooling_need_score or 0,
        business_type=lead.business_type or "",
    )
    procurement = procurement_signal_score(lead.ai_signals)
    website_intent = website_intent_score(
        buying_signal=lead.buying_signal,
        ai_signals=lead.ai_signals,
    )

    contacts: List = []
    documents: List = []
    if db is not None:
        contacts = contacts_crud.list_for_lead(db, lead.id)
        documents = doc_crud.get_by_lead(db, lead.id)

    contact_quality = contact_quality_score(contacts)
    pdf_signal = pdf_signal_score(documents)

    lead_score = compute_lead_score(
        company_fit=company_fit,
        procurement_signal=procurement,
        website_intent=website_intent,
        contact_quality=contact_quality,
        pdf_signal=pdf_signal,
    )
    priority = score_to_priority(lead_score)

    breakdown = {
        "company_fit_score": company_fit,
        "procurement_signal_score": procurement,
        "website_intent_score": website_intent,
        "contact_quality_score": contact_quality,
        "pdf_signal_score": pdf_signal,
        "weights": {
            "company_fit": W_COMPANY_FIT,
            "procurement_signal": W_PROCUREMENT,
            "website_intent": W_WEBSITE_INTENT,
            "contact_quality": W_CONTACT_QUALITY,
            "pdf_signal": W_PDF_SIGNAL,
        },
    }

    return {
        "lead_score": lead_score,
        "priority": priority,
        "breakdown": breakdown,
    }


def apply_lead_score(lead: CompanyLead, *, db: Optional[Session] = None) -> Dict:
    """Compute, persist (lead_score / priority / lead_score_breakdown), return."""
    result = score_lead(lead, db=db)
    lead.lead_score = result["lead_score"]
    lead.priority = result["priority"]
    lead.lead_score_breakdown = json.dumps(result["breakdown"], ensure_ascii=False)
    if db is not None:
        db.add(lead)
        db.commit()
        db.refresh(lead)
    return result


__all__ = [
    "company_fit_score",
    "procurement_signal_score",
    "website_intent_score",
    "contact_quality_score",
    "pdf_signal_score",
    "compute_lead_score",
    "score_lead",
    "apply_lead_score",
    "score_to_priority",
    "PRIORITY_HIGH_THRESHOLD",
    "PRIORITY_MEDIUM_THRESHOLD",
    "HIGH",
    "MEDIUM",
    "LOW",
]
