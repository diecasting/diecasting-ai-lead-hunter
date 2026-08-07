"""Role-based sales prompts (Phase 9 AI Sales Agent).

Maps a contact's functional ``title_category`` (from Contact Intelligence's
``classify_title_category``) to a tailored sales narrative: the buyer persona's
priority, the angles that resonate, and a suggested call-to-action theme.

Two consumers:
  * the email personalization engine — uses ``role_prompt`` as the LLM system
    prompt / angle guidance when AI enhancement is enabled;
  * the company research generator — uses ``role_focus`` / ``role_cta`` to
    recommend an outreach angle based on the strongest contact's role.
"""
from typing import Dict, List

# Each entry: LLM system prompt + the persona's priority focus + a suggested CTA.
_ROLE_PROMPTS: Dict[str, Dict[str, str]] = {
    "procurement": {
        "system": (
            "You are a senior B2B sourcing advisor for a precision die casting, "
            "CNC machining and tooling manufacturer. Write for a procurement / "
            "purchasing audience: emphasise total cost of ownership, supply-chain "
            "reliability, capacity, lead times, MOQ flexibility and certifications "
            "(IATF 16949 / ISO 9001). Be concrete and commercial; avoid fluff."
        ),
        "focus": "cost, capacity, lead time, supply reliability, certifications",
        "cta": "propose a quote / supplier-qualification call",
    },
    "engineering": {
        "system": (
            "You are a technical sales engineer for a precision die casting, CNC "
            "machining and tooling manufacturer. Write for an engineering / R&D "
            "audience: emphasise tolerances, material grades, process capability "
            "(thin-wall, high-pressure die casting), DFM, PPAP and prototyping "
            "speed. Be technically precise."
        ),
        "focus": "tolerances, materials, DFM, process capability, PPAP",
        "cta": "propose a technical review / DFM discussion",
    },
    "executive": {
        "system": (
            "You are a strategic account director for a precision die casting, CNC "
            "machining and tooling manufacturer. Write for an executive (CEO / GM "
            "/ VP): emphasise strategic partnership, risk reduction, scaling "
            "capacity and business outcomes. Keep it high-level and concise."
        ),
        "focus": "strategic partnership, risk reduction, scaling, outcomes",
        "cta": "propose a brief executive intro call",
    },
    "operations": {
        "system": (
            "You are an operations-focused sales consultant for a precision die "
            "casting, CNC machining and tooling manufacturer. Write for an "
            "operations / plant audience: emphasise uptime, logistics, consistency "
            "of supply and reducing production bottlenecks."
        ),
        "focus": "uptime, logistics, supply consistency, bottlenecks",
        "cta": "propose a supply-reliability review",
    },
    "sales": {
        "system": (
            "You are a channel sales partner for a precision die casting, CNC "
            "machining and tooling manufacturer. Write for a sales / business "
            "development audience: emphasise mutual growth, co-selling and "
            "commercial opportunity."
        ),
        "focus": "growth, co-selling, commercial opportunity",
        "cta": "propose a partnership discussion",
    },
    "finance": {
        "system": (
            "You are a commercial analyst for a precision die casting, CNC "
            "machining and tooling manufacturer. Write for a finance audience: "
            "emphasise cost savings, payment terms and ROI."
        ),
        "focus": "cost savings, payment terms, ROI",
        "cta": "propose a commercial proposal review",
    },
    "other": {
        "system": (
            "You are an expert B2B industrial sales copywriter for a precision "
            "die casting, CNC machining and tooling manufacturer. Write a clear, "
            "professional, technically grounded cold outreach email. Avoid generic "
            "marketing language and hype words (e.g. 'best-in-class', 'game-changer')."
        ),
        "focus": "capability fit, value, next step",
        "cta": "propose a short discovery call",
    },
}

_DEFAULT_CATEGORY = "other"


def role_prompt(category: str) -> str:
    """LLM system prompt for a ``title_category`` (falls back to ``other``)."""
    return _ROLE_PROMPTS.get((category or "").lower(), _ROLE_PROMPTS[_DEFAULT_CATEGORY])["system"]


def role_focus(category: str) -> str:
    """The persona's priority focus string for a ``title_category``."""
    return _ROLE_PROMPTS.get((category or "").lower(), _ROLE_PROMPTS[_DEFAULT_CATEGORY])["focus"]


def role_cta(category: str) -> str:
    """The suggested call-to-action theme for a ``title_category``."""
    return _ROLE_PROMPTS.get((category or "").lower(), _ROLE_PROMPTS[_DEFAULT_CATEGORY])["cta"]


def available_categories() -> List[str]:
    """All supported role categories."""
    return list(_ROLE_PROMPTS.keys())
