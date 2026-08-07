"""Contact e-mail ranking (Phase 8).

Scores discovered / inferred addresses so the highest-value *individual*
contacts surface first and role / guessed / disposable addresses sink.
"""
from typing import Dict, List, Optional

from app.email_discovery.patterns import classify_email_type

# Base discovery priority by semantic category (before verification blend).
_TYPE_BASE = {"personal": 80, "generic": 65, "role": 45}

# Hard ceiling for unverified *guessed* (pattern-inferred) addresses.
_PATTERN_CAP = 35


def rank_score(
    email: str,
    *,
    email_type: Optional[str] = None,
    verification_status: Optional[str] = None,
    verification_score: Optional[int] = None,
    source: Optional[str] = None,
) -> int:
    """Return a 0–100 discovery priority score for ``email``.

    When a verification score exists it is blended (60%) with the category
    prior (40%); otherwise the category prior alone is used. Guessed
    (pattern-inferred) addresses are capped so they never out-rank verified or
    site-confirmed contacts.
    """
    if email_type is None:
        email_type = classify_email_type(email)
    base = _TYPE_BASE.get(email_type, 60)

    if verification_score is not None:
        score = int(0.6 * verification_score + 0.4 * base)
    else:
        score = base
        # Soft penalty for unverified role mailboxes.
        if email_type == "role":
            score = max(0, score - 10)

    if source == "pattern":
        score = min(score, _PATTERN_CAP)

    return max(0, min(100, score))


def rank_emails(items: List[Dict]) -> List[Dict]:
    """Order e-mail dicts by :func:`rank_score` descending.

    Each item must contain ``email`` and may carry ``email_type``,
    ``verification_status``, ``verification_score`` and ``source``. A computed
    ``rank_score`` is added to every returned dict. Returns new dicts (does not
    mutate the inputs).
    """
    enriched: List[Dict] = []
    for it in items:
        etype = it.get("email_type") or classify_email_type(it["email"])
        rs = rank_score(
            it["email"],
            email_type=etype,
            verification_status=it.get("verification_status"),
            verification_score=it.get("verification_score"),
            source=it.get("source"),
        )
        copy = dict(it)
        copy["email_type"] = etype
        copy["rank_score"] = rs
        enriched.append(copy)
    enriched.sort(key=lambda x: (-x["rank_score"], x["email"]))
    return enriched
