"""Personalization service (Phase 14.2).

Thin DB-aware wrapper around the pure context/prompt builders. Loads our own
active manufacturing capabilities and feeds them into
:func:`build_personalization_context`, then renders the email.

Design constraints (per Phase 14.2 scope):
  * deterministic, no LLM, no external APIs
  * does NOT modify EmailSender / campaign sending / EmailQualityGate
  * does NOT change the database schema (it only *reads* capabilities)
"""
from typing import List, Optional, Sequence, Union

from sqlalchemy.orm import Session

from app.models.manufacturing_capability import ManufacturingCapability
from app.outreach.personalization.context import (
    PersonalizationContext,
    build_personalization_context,
)
from app.outreach.personalization.prompts import (
    PersonalizedEmail,
    generate_personalized_email_prompt,
)


class PersonalizationService:
    """Build personalized outreach drafts for a (company, contact) pair."""

    def __init__(self, db: Session):
        self.db = db

    # -- internal helpers ----------------------------------------------------
    def _load_capabilities(self) -> List[ManufacturingCapability]:
        return (
            self.db.query(ManufacturingCapability)
            .filter(ManufacturingCapability.active.is_(True))
            .all()
        )

    # -- public API ----------------------------------------------------------
    def build_context(
        self,
        company,
        contact,
        capabilities: Optional[Sequence[Union[object, dict]]] = None,
    ) -> PersonalizationContext:
        """Build the context, loading our capabilities from the DB when not supplied."""
        if capabilities is None:
            capabilities = self._load_capabilities()
        return build_personalization_context(
            company, contact, capabilities=capabilities
        )

    def personalize(self, company, contact) -> PersonalizedEmail:
        """Build context and render a structured outreach draft."""
        ctx = self.build_context(company, contact)
        return generate_personalized_email_prompt(ctx)
