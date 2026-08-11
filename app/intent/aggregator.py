"""Phase 16.3: Intent Aggregation Layer — deterministic SignalEvent -> snapshot.

Converts the raw :class:`SignalEvent` ledger (Phase 16.1 + the Phase 16.2
extractors that feed it) into a single per-:class:`CompanyLead` intent snapshot:

  * ``buying_intent_score``  (0-100)  — blended strength of active signals.
  * ``timing_score``         (0-100)  — recency / freshness of the signal mix.
  * ``intent_temperature``   HOT/WARM/COOL/COLD/NONE — combined urgency bucket.
  * ``last_signal_at``       datetime — most recent active signal detected_at.
  * ``intent_source_count``  int      — number of distinct sources contributing.
  * ``intent_sources``       list     — sorted distinct source identifiers.

Hard constraints (Phase 16.3):
  * **Deterministic only** — pure functions of the input signal set + ``now``.
  * **No LLM, no external API, no network calls.**
  * **Read-only with respect to other lead fields** — aggregation never touches
    ``lead_score``, ``sales_priority``, ``priority``, ``buying_signal``, contact
    ranking, or Opportunity logic. The caller (recompute script / API) writes
    only the six snapshot columns.

The scoring math is intentionally simple and explainable so the same inputs
always yield the same snapshot — a prerequisite for idempotent re-runs.
"""
from datetime import datetime, timezone
from typing import List, Optional

from app.intent.service import SignalEventService
from app.models.signal_event import SIGNAL_VALUE_MAX, SIGNAL_VALUE_MIN, SignalEvent


# ---------------------------------------------------------------------------
# Tunable, deterministic constants (documented in docs/phase16_3_audit.md)
# ---------------------------------------------------------------------------
# Timing decay: a signal loses this many timing-points per day of age.
TIMING_DECAY_PER_DAY = 4.0
# A signal older than this (days) contributes zero timing score.
TIMING_FULL_DECAY_DAYS = 25.0

# Confidence placed in the blended strength when only 1 source is present,
# rising toward 1.0 as more *distinct* sources corroborate. A single strong
# RFQ / reply signal is already a high-quality buying indicator, so the floor
# is set high (0.85); extra sources nudge the factor up to a hard 1.0.
SOURCE_CONFIDENCE_FLOOR = 0.85
SOURCE_CONFIDENCE_MAX = 1.0
SOURCE_CONFIDENCE_PER_SOURCE = 0.05

# Temperature thresholds (applied to buying_intent_score weighted by timing).
TEMP_HOT = 70
TEMP_WARM = 50
TEMP_COOL = 30
# Below TEMP_COOL -> COLD (unless no signals at all -> NONE).

TEMP_HOT_LABEL = "HOT"
TEMP_WARM_LABEL = "WARM"
TEMP_COOL_LABEL = "COOL"
TEMP_COLD_LABEL = "COLD"
TEMP_NONE_LABEL = "NONE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _age_days(detected_at: datetime, now: datetime) -> float:
    """Positive age in days between detected_at and now (never negative)."""
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (now - detected_at).total_seconds()
    return max(0.0, delta / 86400.0)


def _signal_timing_score(detected_at: datetime, now: datetime) -> float:
    """Recency score 0-100: linear decay, floored at 0 after full decay."""
    age = _age_days(detected_at, now)
    if age >= TIMING_FULL_DECAY_DAYS:
        return 0.0
    return _clamp(100.0 - age * TIMING_DECAY_PER_DAY, 0.0, 100.0)


def _source_confidence_factor(distinct_sources: int) -> float:
    """How much we trust the blended strength given corroboration count."""
    if distinct_sources <= 0:
        return 0.0
    return _clamp(
        SOURCE_CONFIDENCE_FLOOR
        + (distinct_sources - 1) * SOURCE_CONFIDENCE_PER_SOURCE,
        SOURCE_CONFIDENCE_FLOOR,
        SOURCE_CONFIDENCE_MAX,
    )


def _normalized_strength(value: Optional[int]) -> float:
    """Map signed SignalEvent.value (-100..+100) onto 0..100 strength scale.

    Positive values scale 0..+100 -> 50..100; negative values scale 0..-100 ->
    0..50 (a strong deterrent pulls the strength down). Deterministic.
    """
    if value is None:
        return 50.0  # unknown strength sits at neutral
    v = _clamp(float(value), SIGNAL_VALUE_MIN, SIGNAL_VALUE_MAX)
    # value == 0 -> 50; value == +100 -> 100; value == -100 -> 0
    return 50.0 + (v / 100.0) * 50.0


def classify_temperature(buying_intent_score: float, timing_score: float) -> str:
    """Bucket (buying_intent_score, timing_score) into a temperature label.

    Uses the *effective* intent = strength gated by how fresh it is, so an old
    but strong signal cools down. Returns one of HOT/WARM/COOL/COLD/NONE.
    """
    if buying_intent_score <= 0:
        return TEMP_NONE_LABEL
    effective = (buying_intent_score / 100.0) * (timing_score / 100.0) * 100.0
    # Strict, non-overlapping bands (a score exactly on a boundary lands in the
    # *higher* band, e.g. effective == 50 -> WARM, == 30 -> COOL).
    if effective >= TEMP_HOT:
        return TEMP_HOT_LABEL
    if effective >= TEMP_WARM:
        return TEMP_WARM_LABEL
    if effective >= TEMP_COOL:
        return TEMP_COOL_LABEL
    return TEMP_COLD_LABEL


class IntentSnapshot:
    """Deterministic aggregation result for one company's active signals."""

    __slots__ = (
        "buying_intent_score",
        "timing_score",
        "intent_temperature",
        "last_signal_at",
        "intent_source_count",
        "intent_sources",
    )

    def __init__(
        self,
        buying_intent_score: int,
        timing_score: int,
        intent_temperature: str,
        last_signal_at: Optional[datetime],
        intent_source_count: int,
        intent_sources: List[str],
    ) -> None:
        self.buying_intent_score = buying_intent_score
        self.timing_score = timing_score
        self.intent_temperature = intent_temperature
        self.last_signal_at = last_signal_at
        self.intent_source_count = intent_source_count
        self.intent_sources = intent_sources

    def as_dict(self) -> dict:
        return {
            "buying_intent_score": self.buying_intent_score,
            "timing_score": self.timing_score,
            "intent_temperature": self.intent_temperature,
            "last_signal_at": self.last_signal_at,
            "intent_source_count": self.intent_source_count,
            "intent_sources": list(self.intent_sources),
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<IntentSnapshot score={self.buying_intent_score} "
            f"timing={self.timing_score} temp={self.intent_temperature!r} "
            f"sources={self.intent_source_count}>"
        )


def aggregate_signals(signals: List[SignalEvent], now: Optional[datetime] = None) -> IntentSnapshot:
    """Pure deterministic aggregation of active signals into an IntentSnapshot.

    ``signals`` is expected to be the *active* signal set for one company (the
    caller filters ``is_active`` and non-expired). Pure function of its inputs:
    same signal list + ``now`` always yields the same snapshot.
    """
    now = now or _now()

    if not signals:
        return IntentSnapshot(
            buying_intent_score=0,
            timing_score=0,
            intent_temperature=TEMP_NONE_LABEL,
            last_signal_at=None,
            intent_source_count=0,
            intent_sources=[],
        )

    # Distinct sources (case-insensitive, deterministic sort).
    sources = sorted({s.source for s in signals if s.source})
    distinct_count = len(sources)

    # --- timing: average recency across signals (freshness of the mix) ------
    timing_sum = 0.0
    last_signal_at: Optional[datetime] = None
    for s in signals:
        timing_sum += _signal_timing_score(s.detected_at, now)
        if s.detected_at is not None:
            if last_signal_at is None or s.detected_at > last_signal_at:
                last_signal_at = s.detected_at
    timing_score = round(_clamp(timing_sum / len(signals), 0.0, 100.0))

    # --- strength: confidence-weighted average of normalized signed value ---
    weighted = 0.0
    weight_total = 0.0
    for s in signals:
        strength = _normalized_strength(s.value)
        conf = (s.confidence if s.confidence is not None else 50) / 100.0
        weighted += strength * conf
        weight_total += conf
    base_strength = (weighted / weight_total) if weight_total > 0 else 50.0

    # Corroboration factor scales the final score (more sources -> more trust).
    factor = _source_confidence_factor(distinct_count)
    buying_intent_score = round(_clamp(base_strength * factor, 0.0, 100.0))

    temperature = classify_temperature(buying_intent_score, timing_score)

    return IntentSnapshot(
        buying_intent_score=buying_intent_score,
        timing_score=timing_score,
        intent_temperature=temperature,
        last_signal_at=last_signal_at,
        intent_source_count=distinct_count,
        intent_sources=sources,
    )


class IntentAggregator:
    """Service facade: loads active signals per company and aggregates them.

    Deterministic, no LLM, no external API, no network. The service only *reads*
    SignalEvent rows; persisting the resulting snapshot to CompanyLead is the
    caller's responsibility (and must be limited to the six snapshot columns).
    """

    def __init__(self, db) -> None:
        self.db = db
        self._service = SignalEventService(db)

    def aggregate_for_company(
        self, company_id: int, now: Optional[datetime] = None
    ) -> IntentSnapshot:
        """Aggregate all active signals attached to ``company_id``."""
        signals = self._service.active_for_company(company_id)
        return aggregate_signals(signals, now=now)

    def aggregate_many(
        self, company_ids: List[int], now: Optional[datetime] = None
    ) -> dict:
        """Return ``{company_id: IntentSnapshot}`` for several companies."""
        return {cid: self.aggregate_for_company(cid, now=now) for cid in company_ids}
