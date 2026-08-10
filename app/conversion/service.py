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
from app.conversion import temperature as temperature_engine
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

    def recompute_temperature(self, lead_id: int) -> ConversionSignal:
        """Recompute and upsert the lead's deterministic temperature.

        Reads the lead's existing intent score (recomputing it if the signal row
        does not yet carry one) plus recency, engagement telemetry, and the best
        contact ranking, then stores ``temperature_score`` / ``temperature_label``
        / ``temperature_reason`` on the (same) one-row-per-lead
        :class:`ConversionSignal`. Returns the persisted row.
        """
        signal = (
            self.db.query(ConversionSignal)
            .filter(ConversionSignal.lead_id == lead_id)
            .first()
        )
        if signal is None:
            signal = ConversionSignal(lead_id=lead_id)
            self.db.add(signal)

        # Reuse the persisted intent score when present; otherwise fall back to
        # a fresh deterministic recompute so temperature never hard-depends on a
        # prior intent pass.
        intent_score = signal.intent_score
        result = temperature_engine.compute_temperature(
            self.db, lead_id, intent_score=intent_score
        )

        signal.temperature_score = result.temperature_score
        signal.temperature_label = result.temperature_label
        signal.temperature_reason = result.temperature_reason
        from datetime import datetime, timezone

        signal.computed_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(signal)
        return signal

    def recompute(self, lead_id: int) -> ConversionSignal:
        """Run both engines (intent + temperature) in one call.

        Convenience for the future reply-analysis / scheduler wiring: keeps the
        single one-row-per-lead :class:`ConversionSignal` fully populated.
        """
        self.recompute_intent_score(lead_id)
        return self.recompute_temperature(lead_id)

    def get_signal(self, lead_id: int) -> Optional[ConversionSignal]:
        """Return the latest :class:`ConversionSignal` for a lead, if any."""
        return (
            self.db.query(ConversionSignal)
            .filter(ConversionSignal.lead_id == lead_id)
            .first()
        )
