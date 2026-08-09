"""Contact Discovery Engine (Phase 13.2).

Discover and enrich company contacts from four sources (website / PDF / role
inbox) without touching the outreach pipeline or creating new tables.
"""
from app.contact_discovery.role_patterns import (
    generate_role_inbox_emails,
    role_inbox_category,
    role_inbox_label,
)
from app.contact_discovery.scoring import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    classify_confidence,
    score_discovery,
)
from app.contact_discovery.service import ContactDiscoveryService

__all__ = [
    "ContactDiscoveryService",
    "generate_role_inbox_emails",
    "role_inbox_category",
    "role_inbox_label",
    "score_discovery",
    "classify_confidence",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
]
