"""Personalized outreach preparation (Phase 14.2).

Deterministic layer that turns a (company, contact) pair plus our own
manufacturing capabilities into a structured, ready-to-send outreach draft
(subject / body / personalization_reason / personalization_score). No LLM, no
network, no external APIs.
"""
from app.outreach.personalization.context import (
    PersonalizationContext,
    build_personalization_context,
)
from app.outreach.personalization.prompts import (
    PersonalizedEmail,
    generate_personalized_email_prompt,
)
from app.outreach.personalization.service import PersonalizationService

__all__ = [
    "PersonalizationContext",
    "PersonalizedEmail",
    "PersonalizationService",
    "build_personalization_context",
    "generate_personalized_email_prompt",
]
