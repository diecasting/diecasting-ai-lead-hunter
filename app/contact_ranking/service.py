"""Contact Ranking Engine service (Phase 14.1).

Wraps :func:`app.contact_ranking.scorer.compute_ranking` and persists the result
onto a :class:`~app.models.contact.Contact` as ``ranking_score`` /
``ranking_confidence`` / ``ranking_reason``. Provides ranked ordering of a
company's contacts *before* outreach selection runs.

Design constraints (per Phase 14.1 scope):
  * deterministic — no LLM, no network, no external APIs
  * does NOT touch the Phase 13.2 ``discovery_score`` / ``confidence`` fields
  * does NOT modify outreach sending logic
  * ``company_id`` is the ``CompanyLead.id`` (the column the rest of the system
    calls ``company_id`` on ``email_addresses`` / ``contact_discovery_logs``)
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.contact_ranking.scorer import compute_ranking
from app.crud import contacts as contacts_crud
from app.models.contact import Contact
from app.models.email_address import EmailAddress


class ContactRankingService:
    """Rank existing contacts for outreach prioritisation."""

    def __init__(self, db: Session):
        self.db = db

    # -- internal helpers ----------------------------------------------------
    def _email_address_for(self, contact: Contact) -> Optional[EmailAddress]:
        if contact.email_address_id is None:
            return None
        return (
            self.db.query(EmailAddress)
            .filter(EmailAddress.id == contact.email_address_id)
            .first()
        )

    def _apply(self, contact: Contact) -> Contact:
        email_address = self._email_address_for(contact)
        result = compute_ranking(contact, email_address=email_address)
        contact.ranking_score = result.score
        contact.ranking_confidence = result.confidence
        contact.ranking_reason = result.reason
        self.db.add(contact)
        return contact

    # -- public API ----------------------------------------------------------
    def rank_contact(self, contact: Contact) -> Contact:
        """Score one contact, persist and return it.

        The caller passes the ORM object (already attached to ``self.db``).
        """
        self._apply(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def rank_company_contacts(self, company_id: int) -> List[Contact]:
        """Score every contact for ``company_id`` and return them sorted.

        Returns contacts ordered by ``ranking_score`` descending (``None``
        scores sink to the bottom). All updates are committed in a single
        transaction at the end of the pass.
        """
        contacts = contacts_crud.list_for_lead(self.db, company_id)
        for c in contacts:
            self._apply(c)
        self.db.commit()
        for c in contacts:
            self.db.refresh(c)
        contacts.sort(
            key=lambda c: (c.ranking_score if c.ranking_score is not None else -1),
            reverse=True,
        )
        return contacts
