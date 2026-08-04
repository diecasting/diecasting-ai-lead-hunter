"""Rule-based lead scoring for the die-casting industry (Phase 2.3).

``casting_need_score`` is a fully deterministic, transparent score (0–100) derived
from hard-coded industry rules. It requires **no API key**, which keeps the
scoring testable and cheap to run at scale. The LLM (OpenAI) is only used later
to enrich the natural-language summary, not the score itself.

Scoring rules
-------------
- Automotive            +30
- EV / Electric vehicle +30
- Aluminum parts        +25
- Magnesium             +25
- CNC                   +15
- OEM                   +15
(capped at 100)

``sales_priority`` thresholds: HIGH ≥ 80, MEDIUM ≥ 50, LOW < 50.
"""
from typing import Dict, List, Optional

# Ordered rules: (needle, weight). A rule contributes once even if it matches
# multiple times. Needles are matched case-insensitively against the text.
SCORING_RULES: List[tuple] = [
    ("automotive", 30),
    ("ev", 30),
    ("electric vehicle", 30),
    ("aluminum", 25),
    ("aluminium", 25),
    ("magnesium", 25),
    ("cnc", 15),
    ("oem", 15),
]

# Product / capability terms used to summarise what a company makes.
PRODUCT_TERMS = [
    "die casting",
    "die-casting",
    "aluminum casting",
    "aluminium casting",
    "magnesium casting",
    "zinc casting",
    "high pressure die casting",
    "hpdc",
    "investment casting",
    "sand casting",
    "cnc machining",
    "precision machining",
    "cnc milling",
    "cnc turning",
    "mold",
    "mould",
    "tooling",
    "motor housing",
    "gearbox housing",
    "structural casting",
]

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 50

# Human-readable signal labels (singular form) for the buying-signal text.
SIGNAL_LABELS = {
    "automotive": "automotive / Tier-1 exposure",
    "ev": "electric-vehicle (EV) programs",
    "electric vehicle": "electric-vehicle (EV) programs",
    "aluminum": "aluminum parts demand",
    "aluminium": "aluminium parts demand",
    "magnesium": "magnesium lightweighting",
    "cnc": "CNC precision machining",
    "oem": "OEM / contract-manufacturing model",
}


def _matched_rules(text: str) -> List[str]:
    lowered = (text or "").lower()
    matched = []
    for needle, _ in SCORING_RULES:
        if needle in lowered:
            matched.append(needle)
    return matched


def casting_need_score(text: str) -> int:
    """Compute the 0–100 casting-need score for a block of text."""
    score = 0
    for needle, weight in SCORING_RULES:
        if needle in (text or "").lower():
            score += weight
    return max(0, min(100, score))


def sales_priority(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def detect_products(text: str, limit: int = 6) -> List[str]:
    lowered = (text or "").lower()
    found = []
    for term in PRODUCT_TERMS:
        if term in lowered and term not in found:
            found.append(term)
            if len(found) >= limit:
                break
    return found


def build_analysis(
    *,
    company: str = "",
    country: str = "",
    industry: str = "",
    text: str = "",
) -> Dict:
    """Build the full Phase 2.3 analysis payload (rule-based, no API needed).

    Returns the structured object:
        {company, country, industry, products, casting_need_score,
         buying_signal, recommended_contact, sales_priority}
    """
    score = casting_need_score(text)
    priority = sales_priority(score)
    matched = _matched_rules(text)

    products = detect_products(text)
    products_str = ", ".join(products) if products else (industry or "Die casting")

    if matched:
        signals = "; ".join(SIGNAL_LABELS.get(m, m) for m in matched)
        buying_signal = (
            f"Strong fit ({score}/100): shows {signals}. "
            "Likely needs die-cast / CNC components."
        )
    else:
        buying_signal = (
            f"Low casting-need signal ({score}/100): little evidence of "
            "die-casting / CNC requirements. Qualify before outreach."
        )

    recommended_contact = "Sales / Business Development team"
    # Prefer a concrete sales mailbox if present in the crawled text.
    import re

    m = re.search(r"(sales|info|export|quote)@[a-z0-9.\-]+\.[a-z]{2,}", (text or "").lower())
    if m:
        recommended_contact = m.group(0)

    final_industry = industry or "Die casting / Precision manufacturing"

    return {
        "company": company or "",
        "country": country or "",
        "industry": final_industry,
        "products": products_str,
        "casting_need_score": score,
        "buying_signal": buying_signal,
        "recommended_contact": recommended_contact,
        "sales_priority": priority,
    }
