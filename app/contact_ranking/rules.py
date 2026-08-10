"""Deterministic ranking rule functions (Phase 14.1 Contact Ranking Engine).

Pure, side-effect-free scoring helpers. Each rule returns an integer
contribution to the final 0-100 ``ranking_score``. No network, no LLM, so the
blend is fully reproducible and unit-testable.

Signal blend (capped to 0-100 by the scorer):

  * role/title          : 0-40  -- functional category + seniority
  * email type          : 0-25  -- personal > generic > role > none
  * verification        : 0-25  -- valid > risky > unverified/unknown > invalid
  * manufacturing fit   : 0-10  -- procurement / engineering / shop-floor title

The Contact Ranking Engine deliberately *re-uses* the existing title
classification (``app.contact_intelligence.titles``) and e-mail classification
(``app.email_discovery.patterns``) rather than inventing new heuristics.
"""
from typing import Optional, Tuple

from app.contact_intelligence.titles import (
    classify_title_category,
    detect_seniority,
)
from app.email_discovery.patterns import classify_email_type
from app.models.contact import (
    CATEGORY_ENGINEERING,
    CATEGORY_EXECUTIVE,
    CATEGORY_FINANCE,
    CATEGORY_OPERATIONS,
    CATEGORY_OTHER,
    CATEGORY_PROCUREMENT,
    CATEGORY_SALES,
    SENIORITY_EXECUTIVE,
    SENIORITY_JUNIOR,
    SENIORITY_MID,
    SENIORITY_SENIOR,
    SENIORITY_UNKNOWN,
)
from app.models.email_address import (
    VERIFICATION_INVALID,
    VERIFICATION_RISKY,
    VERIFICATION_UNKNOWN,
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VALID,
)

# --- role / title component (0-40) ------------------------------------------
_ROLE_CATEGORY_SCORE = {
    CATEGORY_PROCUREMENT: 25,
    CATEGORY_EXECUTIVE: 22,
    CATEGORY_ENGINEERING: 20,
    CATEGORY_OPERATIONS: 15,
    CATEGORY_SALES: 12,
    CATEGORY_FINANCE: 8,
    CATEGORY_OTHER: 5,
}

_ROLE_SENIORITY_SCORE = {
    SENIORITY_EXECUTIVE: 15,
    SENIORITY_SENIOR: 12,
    SENIORITY_MID: 8,
    SENIORITY_JUNIOR: 4,
    SENIORITY_UNKNOWN: 6,
}

# --- email type component (0-25) --------------------------------------------
_EMAIL_TYPE_SCORE = {
    "personal": 25,
    "generic": 15,
    "role": 8,
}
_EMAIL_TYPE_NONE = 0

# --- verification component (0-25) ------------------------------------------
_VERIFICATION_SCORE = {
    VERIFICATION_VALID: 25,
    VERIFICATION_RISKY: 12,
    VERIFICATION_UNVERIFIED: 5,
    VERIFICATION_UNKNOWN: 5,
    VERIFICATION_INVALID: 0,
}
_VERIFICATION_NONE = 0

# --- manufacturing relevance component (0-10) ------------------------------
# Substring keywords that indicate a die-casting / manufacturing buying or
# technical role. ``procurement`` and ``engineering`` categories are handled
# separately (see :func:`manufacturing_relevance_score`).
_MFG_KEYWORDS = [
    "purchasing", "procurement", "buyer", "sourcing", "supply chain",
    "supply-chain", "vendor", "supplier", "materials",
    "engineering", "technical", "tooling", "tool", "manufacturing",
    "production", "quality", "process", "cad", "cam", "mechanical",
    "industrial", "die casting", "die-casting", "diecast", "cnc",
    "machining", "machinist", "foundry", "casting", "mold", "mould",
    "r&d", "research", "design",
]


def classify_role(title: Optional[str], role: Optional[str]) -> Tuple[str, str]:
    """Return ``(category, seniority)`` for a contact's title/role text."""
    text = (title or role) or ""
    return classify_title_category(text), detect_seniority(text)


def role_title_score(title: Optional[str], role: Optional[str]) -> int:
    """Role/title contribution (0-40) from functional category + seniority."""
    cat, sen = classify_role(title, role)
    return _ROLE_CATEGORY_SCORE.get(cat, 5) + _ROLE_SENIORITY_SCORE.get(sen, 6)


def email_type_score(email: Optional[str]) -> int:
    """E-mail semantic-type contribution (0-25)."""
    if not email:
        return _EMAIL_TYPE_NONE
    etype = classify_email_type(email)
    return _EMAIL_TYPE_SCORE.get(etype, _EMAIL_TYPE_NONE)


def verification_score(status: Optional[str]) -> int:
    """Verification-status contribution (0-25). ``None`` -> 0."""
    if not status:
        return _VERIFICATION_NONE
    return _VERIFICATION_SCORE.get(status, _VERIFICATION_NONE)


def manufacturing_relevance_score(
    title: Optional[str] = None,
    role: Optional[str] = None,
    title_category: str = CATEGORY_OTHER,
) -> int:
    """Manufacturing-fit contribution (0-10).

    A contact is manufacturing-relevant when its classified category is
    ``procurement`` or ``engineering`` (the two most die-casting-relevant
    functions), or when its free text contains a shop-floor / manufacturing
    keyword (CNC, tooling, casting, foundry, …).
    """
    if title_category in (CATEGORY_PROCUREMENT, CATEGORY_ENGINEERING):
        return 10
    text = f"{title or ''} {role or ''}".lower()
    if any(kw in text for kw in _MFG_KEYWORDS):
        return 10
    return 0
