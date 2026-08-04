"""Lead ranking engine (Phase 2.3, section 5).

Translates the three need-scores (casting / cnc / tooling) into an actionable
``sales_priority`` label and a single sortable ``rank_score``.

Priority rules
---------------
* HIGH    — best score ≥ 80
* MEDIUM  — best score 50–79
* LOW     — best score < 50
"""
from typing import Dict, Optional

from app.ai.scoring import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    sales_priority,
)


def primary_score(
    casting_need_score: int = 0,
    cnc_need_score: int = 0,
    tooling_need_score: int = 0,
) -> int:
    """The strongest single demand signal across the three process families."""
    return max(
        int(casting_need_score or 0),
        int(cnc_need_score or 0),
        int(tooling_need_score or 0),
    )


def score_to_priority(score: int) -> str:
    """Map a single 0–100 score to a sales-priority label."""
    return sales_priority(int(score or 0))


def rank_lead(scores: Dict[str, int]) -> str:
    """Compute ``sales_priority`` from a ``{casting, cnc, tooling}`` score dict."""
    best = primary_score(
        casting_need_score=scores.get("casting_need_score", 0),
        cnc_need_score=scores.get("cnc_need_score", 0),
        tooling_need_score=scores.get("tooling_need_score", 0),
    )
    return score_to_priority(best)


def rank_with_detail(
    casting_need_score: int = 0,
    cnc_need_score: int = 0,
    tooling_need_score: int = 0,
) -> Dict[str, object]:
    """Return both the priority label and the underlying primary score."""
    best = primary_score(casting_need_score, cnc_need_score, tooling_need_score)
    return {
        "priority": score_to_priority(best),
        "primary_score": best,
        "casting_need_score": int(casting_need_score or 0),
        "cnc_need_score": int(cnc_need_score or 0),
        "tooling_need_score": int(tooling_need_score or 0),
    }


# Convenience constants re-exported for callers that import from ranking only.
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

__all__ = [
    "rank_lead",
    "rank_with_detail",
    "score_to_priority",
    "primary_score",
    "HIGH_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "HIGH",
    "MEDIUM",
    "LOW",
]
