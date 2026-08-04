"""Email confidence scoring (Phase 4 Stage 1).

Combines the verification verdict, the verifier's own 0–100 score, and the
*role relevance* of the associated contact into a single ``confidence`` score
(0–100). The confidence score is what the contact selector and the outreach
router use to pick the best recipient and to decide whether a send is worth it.

The score is deliberately conservative: an INVALID verdict floors confidence at
0, a RISKY verdict is penalised (but not zeroed — risky emails can still be
sent per the Stage 1 "risky != block" policy), and a well-matched role
(Purchasing / Sourcing / Supplier Quality / Engineering) lifts confidence.
"""
from typing import Optional

from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    VerificationResult,
)

# Per-verdict baseline contribution to confidence.
_VERDICT_BASE = {
    VALID: 70,
    UNKNOWN: 45,
    RISKY: 30,
    INVALID: 0,
}

# Role relevance bonus: how much a matched buying-role adds to confidence.
# These mirror the Stage 1 contact-selection priority list.
_ROLE_BONUS = {
    "purchasing manager": 20,
    "strategic sourcing": 18,
    "strategic sourcing manager": 18,
    "supplier quality": 16,
    "supplier quality manager": 16,
    "engineering manager": 14,
    "engineering": 14,
    "supply chain": 12,
    "buyer": 12,
    "procurement": 12,
}


def _normalise_role(role: Optional[str]) -> str:
    return (role or "").strip().lower()


def role_bonus(role: Optional[str]) -> int:
    """Return the confidence bonus for a contact role (0 if unrecognised)."""
    r = _normalise_role(role)
    if not r:
        return 0
    if r in _ROLE_BONUS:
        return _ROLE_BONUS[r]
    # Partial match (e.g. "Senior Purchasing Manager").
    for key, value in _ROLE_BONUS.items():
        if key in r:
            return value
    return 0


def score_email_confidence(
    email: str,
    verification: Optional[VerificationResult] = None,
    *,
    role: Optional[str] = None,
    has_email: bool = True,
    is_primary: bool = False,
    do_not_contact: bool = False,
) -> int:
    """Compute a 0–100 confidence score for sending to ``email``.

    Args:
        email: The address (used only for sanity; presence implied by caller).
        verification: A :class:`VerificationResult` from a verifier / gate.
        role: The associated contact's role/title (relevance boost).
        has_email: Whether the contact actually carries an e-mail (else 0).
        is_primary: Primary contact flag adds a small bonus.
        do_not_contact: A do_not_contact contact floors confidence at 0.

    Returns:
        int 0–100.
    """
    if do_not_contact:
        return 0
    if not has_email or not email:
        return 0

    verdict = verification.status if verification is not None else UNKNOWN
    base = _VERDICT_BASE.get(verdict, _VERDICT_BASE[UNKNOWN])

    # Blend the verifier's own score when present (0–100).
    if verification is not None and verification.score is not None:
        # 60% verdict base, 40% provider score.
        base = int(base * 0.6 + max(0, min(100, verification.score)) * 0.4)

    score = base + role_bonus(role)
    if is_primary:
        score += 5

    return max(0, min(100, score))


def confidence_label(score: int) -> str:
    """Bucket a confidence score into a human label."""
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 30:
        return "low"
    return "very_low"
