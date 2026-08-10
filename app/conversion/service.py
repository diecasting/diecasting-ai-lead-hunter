"""Conversion intelligence service (Phase 15.1.1 / 15.1.2).

Owns persistence of :class:`ConversionSignal` rows and orchestrates the
deterministic intent-score engine (:mod:`app.conversion.intent`).

This is a *read-and-write* layer over existing data only — it never touches
the outreach send path, the email quality gate, opportunity stages, or campaign
sending. It is safe to call from the reply-analysis pipeline or a future
scheduler; all DB work is isolated by the caller's transaction.

Usage::

    svc = ConversionService(db)
    signal = svc.recompute_intent_score(lead_id)
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.conversion import intent as intent_engine
from app.models.conversion_signal import ConversionSignal


class ConversionService:
    """Compute and persist conversion-intelligence signals for a lead."""

    def __init__(self, db: Session):
        self.db = db

    def recompute_intent_score(self, lead_id: int) -> ConversionSignal:
        """Recompute and upsert the lead's intent score.

        One :class:`ConversionSignal` row per lead: if one already exists it is
        updated in place, otherwise a new row is created. Returns the persisted
        row (with its ``id`` populated).
        """
        result = intent_engine.compute_intent_score(self.db, lead_id)

        existing = (
            self.db.query(ConversionSignal)
            .filter(ConversionSignal.lead_id == lead_id)
            .first()
        )
        if existing is None:
            signal = ConversionSignal(lead_id=lead_id)
            self.db.add(signal)
        else:
            signal = existing

        signal.intent_score = result.intent_score
        signal.dominant_intent = result.dominant_intent
        signal.signal_sources = json.dumps(
            result.signal_sources, ensure_ascii=False, default=str
        )
        # computed_at is server-defaulted on insert; refresh on update so the
        # caller sees the new timestamp.
        from datetime import datetime, timezone

        signal.computed_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(signal)
        return signal

    def get_signal(self, lead_id: int) -> Optional[ConversionSignal]:
        """Return the latest :class:`ConversionSignal` for a lead, if any."""
        return (
            self.db.query(ConversionSignal)
            .filter(ConversionSignal.lead_id == lead_id)
            .first()
        )
