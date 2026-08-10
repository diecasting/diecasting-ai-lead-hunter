"""Phase 16.1: SignalEvent repository (thin DB access).

No business logic, no dedup decisions, no external I/O — just CRUD + queries
against the ``signal_events`` table. The dedup / upsert policy lives in
:mod:`app.intent.service`.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.signal_event import SignalEvent


class SignalEventRepository:
    """Thin persistence layer for :class:`SignalEvent`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- reads ---------------------------------------------------------------
    def get_by_id(self, signal_id: int) -> Optional[SignalEvent]:
        return (
            self.db.query(SignalEvent)
            .filter(SignalEvent.id == signal_id)
            .first()
        )

    def get_by_dedup_key(self, dedup_key: str) -> Optional[SignalEvent]:
        return (
            self.db.query(SignalEvent)
            .filter(SignalEvent.dedup_key == dedup_key)
            .first()
        )

    def active_for_company(self, company_id: int) -> List[SignalEvent]:
        return (
            self.db.query(SignalEvent)
            .filter(
                SignalEvent.company_id == company_id,
                SignalEvent.is_active.is_(True),
            )
            .all()
        )

    def active_for_opportunity(self, opportunity_id: int) -> List[SignalEvent]:
        return (
            self.db.query(SignalEvent)
            .filter(
                SignalEvent.opportunity_id == opportunity_id,
                SignalEvent.is_active.is_(True),
            )
            .all()
        )

    def active_for_contact(self, contact_id: int) -> List[SignalEvent]:
        return (
            self.db.query(SignalEvent)
            .filter(
                SignalEvent.contact_id == contact_id,
                SignalEvent.is_active.is_(True),
            )
            .all()
        )

    def count(self) -> int:
        return self.db.query(SignalEvent).count()

    # --- writes --------------------------------------------------------------
    def create(self, **kwargs) -> SignalEvent:
        obj = SignalEvent(**kwargs)
        self.db.add(obj)
        self.db.flush()
        return obj

    def expire_stale(self, now: Optional[datetime] = None) -> int:
        """Soft-deactivate signals whose ``expires_at`` is in the past.

        Returns the number of rows flipped to ``is_active = False``.
        """
        now = now or datetime.now(timezone.utc)
        expired = (
            self.db.query(SignalEvent)
            .filter(
                SignalEvent.is_active.is_(True),
                SignalEvent.expires_at.isnot(None),
                SignalEvent.expires_at < now,
            )
            .all()
        )
        for ev in expired:
            ev.is_active = False
        self.db.flush()
        return len(expired)
