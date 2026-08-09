"""Deterministic discovery scoring (Phase 13.2 Contact Discovery Engine).

Produces a single 0-100 ``discovery_score`` for every discovered contact and a
derived ``confidence`` label (high / medium / low). The score is fully
deterministic — no network, no LLM — so it is trivially testable and reproducible.

Signal blend (every component is additive, clamped to 0-100):

  * verification  : valid +30, risky +15, unverified/unknown 0, invalid -50
  * source        : website +20, pdf +15, crm +25, manual +25, pattern +5
  * role/category : procurement +25, engineering +18, executive +15,
                    operations +10, sales +8, finance +5, other 0
  * pattern bonus : +5 when the address was pattern/role-inferred
  * no-email cap  : when a contact has no deliverable e-mail its score is
                    capped at 40 (a name alone is weak signal)

Confidence thresholds: high >= 75, medium >= 55, else low.
"""
from typing import Optional

from app.models.contact import (
    CATEGORY_ENGINEERING,
    CATEGORY_EXECUTIVE,
    CATEGORY_FINANCE,
    CATEGORY_OPERATIONS,
    CATEGORY_OTHER,
    CATEGORY_PROCUREMENT,
    CATEGORY_SALES,
)

# Confidence vocabulary.
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Verification-status bonus (mirrors EmailAddress.VERIFICATION_* vocabulary).
_VERIFICATION_BONUS = {
    "valid": 30,
    "risky": 15,
    "unverified": 0,
    "unknown": 0,
    "invalid": -50,
}

# Discovery-source bonus (keyed by the discovery_method vocabulary).
_SOURCE_BONUS = {
    "website": 20,
    "pdf": 15,
    "crm": 25,
    "manual": 25,
    "pattern": 5,
}

# Title-category bonus.
_CATEGORY_BONUS = {
    CATEGORY_PROCUREMENT: 25,
    CATEGORY_ENGINEERING: 18,
    CATEGORY_EXECUTIVE: 15,
    CATEGORY_OPERATIONS: 10,
    CATEGORY_SALES: 8,
    CATEGORY_FINANCE: 5,
    CATEGORY_OTHER: 0,
}

# Bonus for addresses produced by pattern/role inference (vs site-confirmed).
_PATTERN_BONUS = 5

# Cap applied when a contact has no deliverable e-mail (weak signal).
_NO_EMAIL_CAP = 40

# Confidence label thresholds (inclusive lower bounds).
HIGH_THRESHOLD = 75
MEDIUM_THRESHOLD = 55


def score_discovery(
    *,
    verification_status: Optional[str] = None,
    source: str = "website",
    title_category: str = CATEGORY_OTHER,
    is_pattern: bool = False,
    has_email: bool = True,
) -> int:
    """Return the deterministic 0-100 discovery score for a contact.

    Parameters
    ----------
    verification_status : one of valid/risky/unverified/unknown/invalid (or None)
    source              : discovery method — website/pdf/crm/manual/pattern
    title_category      : classified functional area (procurement, …)
    is_pattern          : True when the address was pattern/role-inferred
    has_email           : True when a deliverable e-mail is attached
    """
    score = 0
    score += _VERIFICATION_BONUS.get(verification_status, 0)
    score += _SOURCE_BONUS.get(source, _SOURCE_BONUS["website"])
    score += _CATEGORY_BONUS.get(title_category, 0)
    if is_pattern:
        score += _PATTERN_BONUS

    # A contact with only a name (no e-mail) is weak signal — cap it.
    if not has_email:
        score = min(score, _NO_EMAIL_CAP)

    return max(0, min(100, score))


def classify_confidence(score: int) -> str:
    """Map a 0-100 discovery score to a confidence label."""
    if score >= HIGH_THRESHOLD:
        return CONFIDENCE_HIGH
    if score >= MEDIUM_THRESHOLD:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW
