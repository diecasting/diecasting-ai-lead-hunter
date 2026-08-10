"""Phase 16.1: deterministic dedup / upsert service for :class:`SignalEvent`.

This is the *only* place that decides whether an incoming observation is new or
an update of an existing one. It is fully deterministic (no randomness, no
network, no LLM) so re-running ingestion over the same inputs converges to the
same table state — a hard requirement for idempotent signal ingestion.

Public API:
  * :class:`SignalInput`  — structured ingest payload (dataclass).
  * :class:`IngestResult` — (signal, created, updated) outcome.
  * :meth:`SignalEventService.ingest`        — dedup + upsert a single signal.
  * :meth:`SignalEventService.ingest_many`   — batch ingest.
  * :meth:`SignalEventService.expire_stale`  — age out expired signals.
  * Query helpers forwarding to the repository.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.intent.repository import SignalEventRepository
from app.models.signal_event import (
    SIGNAL_VALUE_MAX,
    SIGNAL_VALUE_MIN,
    SignalEvent,
    clamp_confidence,
    clamp_signal_value,
)


@dataclass
class SignalInput:
    """Structured payload describing one buying-intent observation.

    Exactly one of ``company_id`` / ``opportunity_id`` / ``contact_id`` should
    normally be set (the entity the signal attaches to).
    """

    source: str
    signal_type: str
    value: int
    company_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    contact_id: Optional[int] = None
    intent_category: Optional[str] = None
    confidence: Optional[int] = None
    raw_value: Optional[str] = None
    external_id: Optional[str] = None
    detected_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    metadata: Optional[dict] = None


@dataclass
class IngestResult:
    signal: SignalEvent
    created: bool
    updated: bool


def _dedup_key(
    company_id: Optional[int],
    opportunity_id: Optional[int],
    contact_id: Optional[int],
    source: str,
    signal_type: str,
    external_id: Optional[str],
) -> str:
    """Deterministic SHA-1 key for idempotent upsert.

    Collapses (entity scope, source, signal_type, external_id) into a single
    40-char hex key. Two observations sharing this tuple are the *same* signal
    occurrence and must not create a second row.
    """
    raw = "|".join(
        [
            str(company_id if company_id is not None else ""),
            str(opportunity_id if opportunity_id is not None else ""),
            str(contact_id if contact_id is not None else ""),
            source or "",
            signal_type or "",
            external_id or "",
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class SignalEventService:
    """Deterministic ingestion + query facade over :class:`SignalEvent`."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SignalEventRepository(db)

    # --- ingestion -----------------------------------------------------------
    def ingest(self, signal: SignalInput) -> IngestResult:
        """Dedup + upsert a single signal. Idempotent for the same dedup key."""
        dedup_key = _dedup_key(
            signal.company_id,
            signal.opportunity_id,
            signal.contact_id,
            signal.source,
            signal.signal_type,
            signal.external_id,
        )

        value = clamp_signal_value(signal.value)
        confidence = clamp_confidence(signal.confidence)
        detected_at = signal.detected_at or datetime.now(timezone.utc)
        metadata_json = (
            json.dumps(signal.metadata, sort_keys=True, ensure_ascii=False)
            if signal.metadata is not None
            else None
        )

        existing = self.repo.get_by_dedup_key(dedup_key)
        if existing is None:
            obj = self.repo.create(
                company_id=signal.company_id,
                opportunity_id=signal.opportunity_id,
                contact_id=signal.contact_id,
                source=signal.source,
                signal_type=signal.signal_type,
                intent_category=signal.intent_category,
                value=value,
                confidence=confidence,
                raw_value=signal.raw_value,
                detected_at=detected_at,
                expires_at=signal.expires_at,
                is_active=True,
                external_id=signal.external_id,
                dedup_key=dedup_key,
                metadata_json=metadata_json,
            )
            return IngestResult(signal=obj, created=True, updated=False)

        # Update the existing active row in place (deterministic upsert).
        existing.value = value
        existing.confidence = confidence
        existing.intent_category = signal.intent_category
        existing.raw_value = signal.raw_value
        existing.detected_at = detected_at
        existing.expires_at = signal.expires_at
        existing.is_active = True
        existing.metadata_json = metadata_json
        self.db.flush()
        return IngestResult(signal=existing, created=False, updated=True)

    def ingest_many(self, signals: List[SignalInput]) -> List[IngestResult]:
        return [self.ingest(s) for s in signals]

    # --- TTL -----------------------------------------------------------------
    def expire_stale(self, now: Optional[datetime] = None) -> int:
        return self.repo.expire_stale(now=now)

    # --- queries -------------------------------------------------------------
    def active_for_company(self, company_id: int) -> List[SignalEvent]:
        return self.repo.active_for_company(company_id)

    def active_for_opportunity(self, opportunity_id: int) -> List[SignalEvent]:
        return self.repo.active_for_opportunity(opportunity_id)

    def active_for_contact(self, contact_id: int) -> List[SignalEvent]:
        return self.repo.active_for_contact(contact_id)
