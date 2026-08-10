"""Contact Ranking Engine (Phase 14.1).

Deterministic outreach-prioritisation scoring for existing contacts. Ranks
contacts by role/title, e-mail type, verification and manufacturing relevance
before the outreach selector runs. No LLM, no external APIs.
"""
from app.contact_ranking.rules import (
    email_type_score,
    manufacturing_relevance_score,
    role_title_score,
    verification_score,
)
from app.contact_ranking.scorer import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    RankingResult,
    compute_ranking,
)
from app.contact_ranking.service import ContactRankingService

__all__ = [
    "ContactRankingService",
    "RankingResult",
    "compute_ranking",
    "role_title_score",
    "email_type_score",
    "verification_score",
    "manufacturing_relevance_score",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
]
