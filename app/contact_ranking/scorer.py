"""Deterministic contact ranking scorer (Phase 14.1 Contact Ranking Engine).

Combines the rule functions in :mod:`app.contact_ranking.rules` into a single
0-100 ``ranking_score`` plus a ``ranking_confidence`` label and a human-readable
``ranking_reason`` string. Fully deterministic and dependency-free (no LLM, no
network, no external APIs).
"""
from dataclasses import dataclass
from typing import Optional

from app.contact_intelligence.titles import (
    classify_title_category,
    detect_seniority,
)
from app.contact_ranking.rules import (
    _ROLE_CATEGORY_SCORE,
    _ROLE_SENIORITY_SCORE,
    email_type_score,
    manufacturing_relevance_score,
    role_title_score,
    verification_score,
)
from app.email_discovery.patterns import classify_email_type
from app.models.contact import CATEGORY_OTHER
from app.models.email_address import VERIFICATION_VALID

# Confidence vocabulary (re-used by the service when persisting).
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Hard 0-100 ceiling for the blended score.
_MAX_SCORE = 100


@dataclass
class RankingResult:
    """Computed ranking for a single contact."""

    score: int
    confidence: str
    reason: str


def compute_ranking(contact, email_address=None) -> RankingResult:
    """Compute the deterministic ranking for ``contact``.

    ``email_address`` is the linked :class:`~app.models.email_address.EmailAddress`
    (when present) used to read the verification verdict. The contact's own
    ``title`` / ``role`` / ``email`` / ``title_category`` fields drive the rest.

    Returns a :class:`RankingResult` — the caller decides whether/how to persist
    it (the service writes it to ``Contact.ranking_*``).
    """
    title = getattr(contact, "title", None) or getattr(contact, "role", None)
    role = getattr(contact, "role", None)
    email = getattr(contact, "email", None)
    title_category = getattr(contact, "title_category", None) or CATEGORY_OTHER

    cat = classify_title_category(title or role)
    sen = detect_seniority(title or role)
    cat_points = _ROLE_CATEGORY_SCORE.get(cat, 5)
    sen_points = _ROLE_SENIORITY_SCORE.get(sen, 6)
    rt = cat_points + sen_points

    et = email_type_score(email)
    vstat = (
        getattr(email_address, "verification_status", None)
        if email_address is not None
        else None
    )
    vs = verification_score(vstat)
    mfg = manufacturing_relevance_score(
        title=title, role=role, title_category=title_category
    )

    raw = rt + et + vs + mfg
    score = max(0, min(_MAX_SCORE, raw))

    has_title = bool(title)
    has_email = bool(email)
    if has_title and has_email:
        confidence = CONFIDENCE_HIGH
    elif has_title or has_email:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    etype = classify_email_type(email) if email else "none"
    verified = vstat == VERIFICATION_VALID
    reason = (
        f"category={cat}(+{cat_points}); "
        f"seniority={sen}(+{sen_points}); "
        f"email_type={etype}(+{et}); "
        f"verification={vstat or 'none'}(+{vs}); "
        f"manufacturing={'relevant' if mfg else 'none'}(+{mfg}); "
        f"verified={verified} => score={score}"
    )
    return RankingResult(score=score, confidence=confidence, reason=reason)
