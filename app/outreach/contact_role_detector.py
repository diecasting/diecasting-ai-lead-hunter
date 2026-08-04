"""Contact role detector — recommends the best contact role(s) to reach
at a target company based on industry, business type, and buying signal.

Each industry maps to one or more recommended roles. The detector also
ranks roles by relevance when a company spans multiple industries.
"""
from typing import Dict, List, Optional, Tuple

# ── Industry → recommended contact roles ──────────────────────────────────
_INDUSTRY_ROLES: Dict[str, List[str]] = {
    "automotive": [
        "Purchasing Manager",
        "Supplier Development Engineer",
        "Global Sourcing Manager",
    ],
    "ev": [
        "Strategic Sourcing Manager",
        "Supply Chain Director",
        "Component Engineering Manager",
    ],
    "electric vehicle": [
        "Strategic Sourcing Manager",
        "Supply Chain Director",
        "Component Engineering Manager",
    ],
    "battery": [
        "Strategic Sourcing Manager",
        "Procurement Engineer",
    ],
    "motor housing": [
        "Engineering Manager",
        "Purchasing Manager",
    ],
    "gearbox": [
        "Purchasing Manager",
        "Engineering Manager",
    ],
    "pump": [
        "Purchasing Manager",
        "OEM Procurement",
    ],
    "hydraulic": [
        "Engineering Manager",
        "OEM Procurement",
        "Purchasing Manager",
    ],
    "robotics": [
        "Engineering Manager",
        "R&D Director",
        "Strategic Sourcing Manager",
    ],
    "industrial equipment": [
        "Engineering Manager",
        "OEM Procurement",
        "Purchasing Manager",
    ],
    "aerospace": [
        "Supply Chain Manager",
        "Quality Assurance Manager",
        "Engineering Manager",
    ],
    "medical": [
        "Regulatory Affairs Manager",
        "Purchasing Manager",
        "Quality Assurance Manager",
    ],
    "cnc machining": [
        "Production Manager",
        "Purchasing Manager",
    ],
    "tooling": [
        "Tooling Manager",
        "Engineering Manager",
        "Purchasing Manager",
    ],
    "mold": [
        "Tooling Manager",
        "Engineering Manager",
    ],
}

# ── Business-type specific overrides ──────────────────────────────────────
_BUSINESS_TYPE_ROLES: Dict[str, List[str]] = {
    "Manufacturer / OEM": [
        "Purchasing Manager",
        "Supplier Development Engineer",
    ],
    "Trader / Distributor": [
        "Sales Director",
        "Product Manager",
    ],
    "Supplier": [
        "Purchasing Manager",
        "Supply Chain Manager",
    ],
}

# ── Buying-signal priority boost ──────────────────────────────────────────
_SIGNAL_PRIORITY_ROLES: Dict[str, List[str]] = {
    "HIGH": [
        "Strategic Sourcing Manager",
        "VP Procurement",
    ],
    "MEDIUM": [
        "Purchasing Manager",
        "Engineering Manager",
    ],
    "LOW": [
        "Sales Manager",
        "General Inquiries",
    ],
}


def _match_industry(industry_text: str) -> List[Tuple[str, int]]:
    """Return matching industry entries with match-length score (longer = better).

    Matches when the dictionary key is a substring of the input OR the input
    is a substring of the key (handles both "cnc" → "cnc machining" and
    "cnc machining → "cnc machining").
    """
    lowered = (industry_text or "").lower()
    results: List[Tuple[str, int]] = []
    for key in _INDUSTRY_ROLES:
        if key in lowered or lowered in key:
            results.append((key, len(key)))
    results.sort(key=lambda x: -x[1])
    return results


def detect_roles(
    industry: str = "",
    business_type: str = "",
    buying_signal: str = "",
    *,
    max_roles: int = 3,
) -> List[str]:
    """Return the top recommended contact roles for the given company profile.

    Roles are ranked by:
    1. Industry-specific roles (exact industry match first, then broad).
    2. Business-type specific roles (as secondary signal).
    3. Buying-signal priority roles (for high-intent leads).

    Args:
        industry: The company's detected industry (e.g. "automotive", "ev").
        business_type: Manufacturer / OEM, Trader / Distributor, Supplier.
        buying_signal: HIGH, MEDIUM, or LOW.
        max_roles: Maximum number of roles to return.
    """
    seen: set = set()
    result: List[str] = []

    def _add(role: str) -> None:
        if role.lower() not in seen:
            seen.add(role.lower())
            result.append(role)

    # 1. Industry-specific roles (primary signal).
    industry_matches = _match_industry(industry)
    for key, _score in industry_matches:
        for role in _INDUSTRY_ROLES.get(key, []):
            _add(role)
            if len(result) >= max_roles:
                return result[:max_roles]

    # 2. Business-type roles (secondary signal).
    if business_type in _BUSINESS_TYPE_ROLES:
        for role in _BUSINESS_TYPE_ROLES[business_type]:
            _add(role)
            if len(result) >= max_roles:
                return result[:max_roles]

    # 3. Buying-signal roles (boost for high-intent leads).
    signal = (buying_signal or "").upper()
    if signal in _SIGNAL_PRIORITY_ROLES:
        for role in _SIGNAL_PRIORITY_ROLES[signal]:
            _add(role)
            if len(result) >= max_roles:
                return result[:max_roles]

    # 4. Fallback.
    for role in ("Purchasing Manager", "Engineering Manager", "General Manager"):
        _add(role)
        if len(result) >= max_roles:
            return result[:max_roles]

    return result[:max_roles]


def detect_primary_role(
    industry: str = "",
    business_type: str = "",
    buying_signal: str = "",
) -> str:
    """Return the single best contact role (the first ranked one)."""
    roles = detect_roles(industry, business_type, buying_signal, max_roles=1)
    return roles[0] if roles else "Purchasing Manager"
