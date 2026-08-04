"""Rule-based lead scoring for the die-casting industry (Phase 2.3).

The engine is fully deterministic and transparent — no API key required — which
keeps scoring cheap, testable, and reproducible at scale. It produces three
independent need-scores plus a buying-signal level:

* ``casting_need_score``  — appetite for aluminium / magnesium die casting.
* ``cnc_need_score``      — appetite for CNC / precision machining.
* ``tooling_need_score``  — appetite for tooling / mould making.

``sales_priority`` thresholds (driven by the *highest* of the three scores):
HIGH ≥ 80, MEDIUM ≥ 50, LOW < 50.

The optional OpenAI LLM is only used later to enrich the natural-language
summary, never the numeric scores.
"""
from typing import Dict, List, Optional, Tuple

from app.ai.keywords import (
    BUYING_SIGNALS,
    INDUSTRIES,
    MATERIALS,
    PROCESSES,
)

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 50

# ---------------------------------------------------------------------------
# Scoring rules: (needle, weight). Each rule contributes once even if it
# matches multiple times. Needles are matched case-insensitively.
# ---------------------------------------------------------------------------
CASTING_RULES: List[Tuple[str, int]] = [
    # Materials
    ("aluminum", 25),
    ("aluminium", 25),
    ("magnesium", 25),
    ("adc12", 15),
    ("a380", 15),
    ("az91", 15),
    ("zamak", 10),
    ("zinc", 10),
    # Casting processes
    ("die casting", 30),
    ("pressure casting", 20),
    ("gravity casting", 20),
    ("sand casting", 15),
    ("investment casting", 15),
    # Demand-driving industries
    ("automotive", 30),
    ("ev", 30),
    ("electric vehicle", 30),
    ("aerospace", 20),
    ("battery", 15),
    ("motor housing", 20),
    ("gearbox", 15),
    ("pump", 10),
    ("hydraulic", 10),
    ("robotics", 10),
    ("industrial equipment", 10),
]

CNC_RULES: List[Tuple[str, int]] = [
    ("cnc machining", 30),
    ("5 axis machining", 30),
    ("precision machining", 25),
    ("machining", 15),
    ("6061", 15),
    ("7075", 15),
    ("cnc", 10),
]

TOOLING_RULES: List[Tuple[str, int]] = [
    ("tooling", 30),
    ("mold", 25),
    ("mould", 25),
    ("tool making", 20),
    ("die cast tool", 20),
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

# Human-readable signal labels for the reason text.
SIGNAL_LABELS = {
    "aluminum": "aluminum parts demand",
    "aluminium": "aluminium parts demand",
    "magnesium": "magnesium lightweighting",
    "die casting": "die-casting capability",
    "pressure casting": "pressure-die-casting capability",
    "gravity casting": "gravity casting",
    "sand casting": "sand casting",
    "investment casting": "investment casting",
    "automotive": "automotive / Tier-1 exposure",
    "ev": "electric-vehicle (EV) programs",
    "electric vehicle": "electric-vehicle (EV) programs",
    "aerospace": "aerospace-grade requirements",
    "battery": "battery / e-mobility components",
    "motor housing": "motor-housing demand",
    "gearbox": "gearbox / transmission parts",
    "pump": "pump / fluid-power parts",
    "hydraulic": "hydraulic components",
    "robotics": "robotics components",
    "industrial equipment": "industrial-equipment parts",
    "cnc machining": "CNC precision machining",
    "5 axis machining": "5-axis machining",
    "precision machining": "precision machining",
    "machining": "machining",
    "6061": "6-series aluminium machining",
    "7075": "7-series aluminium machining",
    "cnc": "CNC machining",
    "tooling": "tooling / mould making",
    "mold": "mould making",
    "mould": "mould making",
    "tool making": "tool making",
    "die cast tool": "die-cast tooling",
}


def _matched_rules(text: str, rules) -> List[str]:
    lowered = (text or "").lower()
    matched = []
    for needle, _ in rules:
        if needle in lowered:
            matched.append(needle)
    return matched


def score_with_rules(text: str, rules) -> int:
    """Sum the weights of every rule whose needle appears in ``text`` (capped 100)."""
    score = 0
    for needle, weight in rules:
        if needle in (text or "").lower():
            score += weight
    return max(0, min(100, score))


def casting_need_score(text: str) -> int:
    """0–100 likelihood the company needs aluminium/magnesium die casting."""
    return score_with_rules(text, CASTING_RULES)


def cnc_need_score(text: str) -> int:
    """0–100 likelihood the company needs CNC / precision machining."""
    return score_with_rules(text, CNC_RULES)


def tooling_need_score(text: str) -> int:
    """0–100 likelihood the company needs tooling / mould making."""
    return score_with_rules(text, TOOLING_RULES)


def sales_priority(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Keyword detection helpers (section 2)
# ---------------------------------------------------------------------------
def detect_materials(text: str, limit: int = 8) -> List[str]:
    lowered = (text or "").lower()
    found = []
    for term in MATERIALS:
        if term in lowered and term not in found:
            found.append(term)
            if len(found) >= limit:
                break
    return found


def detect_processes(text: str, limit: int = 8) -> List[str]:
    lowered = (text or "").lower()
    found = []
    for term in PROCESSES:
        if term in lowered and term not in found:
            found.append(term)
            if len(found) >= limit:
                break
    return found


def detect_industries(text: str, limit: int = 8) -> List[str]:
    lowered = (text or "").lower()
    found = []
    for term in INDUSTRIES:
        if term in lowered and term not in found:
            found.append(term)
            if len(found) >= limit:
                break
    return found


def detect_products(text: str, limit: int = 6) -> List[str]:
    lowered = (text or "").lower()
    found = []
    for term in PRODUCT_TERMS:
        if term in lowered and term not in found:
            found.append(term)
            if len(found) >= limit:
                break
    return found


def business_type(text: str) -> str:
    """Infer whether the company is a manufacturer / OEM, trader or supplier."""
    lowered = (text or "").lower()
    if any(
        k in lowered
        for k in ("distributor", "trader", "wholesale", "reseller", "trading company")
    ):
        return "Trader / Distributor"
    if any(
        k in lowered
        for k in ("manufacturer", "factory", "oem", "production", "maker")
    ):
        return "Manufacturer / OEM"
    if "supplier" in lowered:
        return "Supplier"
    return "Unknown"


def detect_buying_signal(text: str) -> Dict[str, object]:
    """Classify purchase intent (section 3) and return matched phrases.

    Returns ``{"level": "HIGH"|"MEDIUM"|"LOW"|"NONE", "matched": [...], "detail": str}``.
    HIGH wins over MEDIUM over LOW; nothing matched → ``NONE``.
    """
    lowered = (text or "").lower()
    matched: Dict[str, List[str]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for level, phrases in BUYING_SIGNALS.items():
        for phrase in phrases:
            if phrase in lowered and phrase not in matched[level]:
                matched[level].append(phrase)

    if matched["HIGH"]:
        level = "HIGH"
    elif matched["MEDIUM"]:
        level = "MEDIUM"
    elif matched["LOW"]:
        level = "LOW"
    else:
        level = "NONE"

    all_matched = matched["HIGH"] + matched["MEDIUM"] + matched["LOW"]
    detail = "; ".join(all_matched) if all_matched else "no explicit buying signal"
    return {"level": level, "matched": all_matched, "detail": detail}


def build_reason(
    *,
    materials: List[str],
    processes: List[str],
    industries: List[str],
    signal: Dict[str, object],
) -> str:
    """Generate a human-readable rationale for the lead score."""
    parts = []
    if materials:
        parts.append("materials: " + ", ".join(materials[:5]))
    if processes:
        parts.append("processes: " + ", ".join(processes[:5]))
    if industries:
        parts.append("industries: " + ", ".join(industries[:4]))
    if signal["level"] != "NONE":
        parts.append(f"buying signal ({signal['level']}): {signal['detail']}")
    if not parts:
        return (
            "Insufficient website evidence of die-casting / CNC / tooling demand. "
            "Qualify before outreach."
        )
    return "Strong fit indicators — " + "; ".join(parts) + "."


def build_analysis(
    *,
    company: str = "",
    country: str = "",
    industry: str = "",
    text: str = "",
) -> Dict:
    """Build the full Phase 2.3 intelligence payload (rule-based, no API needed).

    Returns the structured object described in the spec:
        company, country, industry, business_type, products, materials,
        manufacturing_process, target_market, casting_need_score,
        cnc_need_score, tooling_need_score, buying_signal, recommended_contact,
        reason, priority.
    """
    casting = casting_need_score(text)
    cnc = cnc_need_score(text)
    tooling = tooling_need_score(text)
    priority = sales_priority(max(casting, cnc, tooling))

    materials = detect_materials(text)
    processes = detect_processes(text)
    industries = detect_industries(text)
    btype = business_type(text)
    signal = detect_buying_signal(text)

    products = detect_products(text)
    products_str = ", ".join(products) if products else (industry or "Die casting")
    target_market = ", ".join(industries[:3]) if industries else "General manufacturing"
    reason = build_reason(
        materials=materials, processes=processes, industries=industries, signal=signal
    )

    # Buying-signal field stores the level plus the matched detail for context.
    buying_signal = signal["level"]
    if signal["matched"]:
        buying_signal = f"{signal['level']} ({signal['detail']})"

    recommended_contact = "Sales / Business Development team"
    import re

    m = re.search(
        r"(sales|info|export|quote|inquiry)@[a-z0-9.\-]+\.[a-z]{2,}", (text or "").lower()
    )
    if m:
        recommended_contact = m.group(0)

    final_industry = industry or "Die casting / Precision manufacturing"

    return {
        "company": company or "",
        "country": country or "",
        "industry": final_industry,
        "business_type": btype,
        "products": products_str,
        "materials": ", ".join(materials),
        "manufacturing_process": ", ".join(processes),
        "target_market": target_market,
        "casting_need_score": casting,
        "cnc_need_score": cnc,
        "tooling_need_score": tooling,
        "buying_signal": buying_signal,
        "recommended_contact": recommended_contact,
        "reason": reason,
        "priority": priority,
    }
