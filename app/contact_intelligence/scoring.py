"""Purchasing priority scoring (Phase 8.5 Contact Intelligence Engine).

Scores how relevant a contact is to a *buying* decision for die-casting
services, combining three signals:

* ``category``  — functional area (procurement weighted highest)
* ``seniority`` — how senior the person is (executives weighted highest)
* ``source``    — how the contact was obtained (CRM / manual = confirmed)

The blend is deterministic and tunable via the module-level weight constants.
The resulting 0-100 score maps to a ``high`` / ``medium`` / ``low`` priority
label used to order outreach.
"""
from typing import Dict

from app.contact_intelligence.titles import classify_title
from app.models.contact import (
    SENIORITY_EXECUTIVE,
    SENIORITY_JUNIOR,
    SENIORITY_MID,
    SENIORITY_SENIOR,
    SENIORITY_UNKNOWN,
)

# Base scores per signal (0-100). Procurement and executives score highest
# because they are the most direct buying-decision influencers.
CATEGORY_SCORE = {
    "procurement": 100,
    "executive": 85,
    "engineering": 75,
    "operations": 70,
    "finance": 60,
    "sales": 50,
    "other": 45,
}

SENIORITY_SCORE = {
    SENIORITY_EXECUTIVE: 100,
    SENIORITY_SENIOR: 80,
    SENIORITY_MID: 55,
    SENIORITY_JUNIOR: 30,
    SENIORITY_UNKNOWN: 50,
}

SOURCE_SCORE = {
    "crm": 100,
    "manual": 95,
    "website": 65,
    "email_pattern": 50,
}

# Weighting of the three signals in the blended score.
_W_CATEGORY = 0.5
_W_SENIORITY = 0.3
_W_SOURCE = 0.2

# Priority label thresholds (inclusive lower bounds).
HIGH_THRESHOLD = 75
MEDIUM_THRESHOLD = 55


def priority_from_score(score: int) -> str:
    """Map a 0-100 purchasing score to a priority label."""
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def score_purchasing(category: str, seniority: str, source: str) -> int:
    """Return a blended 0-100 purchasing-priority score (rounded, clamped)."""
    cat = CATEGORY_SCORE.get(category, CATEGORY_SCORE["other"])
    sen = SENIORITY_SCORE.get(seniority, SENIORITY_SCORE[SENIORITY_UNKNOWN])
    src = SOURCE_SCORE.get(source, SOURCE_SCORE["website"])
    raw = _W_CATEGORY * cat + _W_SENIORITY * sen + _W_SOURCE * src
    return max(0, min(100, round(raw)))


def score_contact(title: str = None, source: str = "website") -> Dict:
    """Classify ``title`` and compute the purchasing score + priority.

    Returns a dict with ``title_category``, ``seniority``, ``purchasing_score``
    and ``priority`` — exactly the intelligence fields stored on a Contact.
    """
    category, seniority = classify_title(title)
    score = score_purchasing(category, seniority, source)
    return {
        "title_category": category,
        "seniority": seniority,
        "purchasing_score": score,
        "priority": priority_from_score(score),
    }
