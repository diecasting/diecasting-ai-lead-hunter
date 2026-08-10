"""Deterministic intent-score engine (Phase 15.1.2).

Consumes a lead's classified customer replies (:class:`ReplyAnalysis`) and its
engagement telemetry (:class:`OutreachEvent`) to produce a single signed
**intent score** (``-100``..``100``) plus the dominant driving intent.

Design rules (strictly deterministic — no LLM, no network):

* Each classified reply contributes ``base_points[intent] * confidence_factor *
  recency_decay``.
  - ``confidence_factor`` = ``confidence_score / 100`` (clamped 0..1).
  - ``recency_decay``    = ``0.5 ** (age_days / HALF_LIFE_DAYS)`` — recent
    replies count fully; older ones decay.
* Engagement telemetry from :class:`OutreachEvent` adds **separate**,
  classification-free signals so it is never double-counted with the reply
  analyses that the analyzer also records:
  - ``opened``  -> small positive (someone is reading the outreach)
  - ``bounced`` -> negative (deliverability problem)
  - ``replied`` / ``sent`` / generation events are ignored here (the classified
    reply already covers ``replied``; outbound events carry no intent).
* The score is clamped to ``[-100, 100]`` and rounded to an integer for storage.
* ``dominant_intent`` is the intent class with the largest *absolute* weighted
  contribution (so a negative lead still reports its strongest negative driver,
  e.g. ``spam``); ``None`` when no classified reply contributed.

Pure helpers (:func:`score_reply`, :func:`score_event`, :func:`recency_decay`)
are exported for offline unit testing of the math without a database.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.lead import CompanyLead
from app.models.outreach_event import OutreachEvent
from app.models.reply_analysis import ReplyAnalysis

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
# Half-life for recency decay (days). A reply 30 days old contributes half of
# a fresh reply with identical intent/confidence.
HALF_LIFE_DAYS = 30

# Base contribution (pre confidence/recency) per reply intent.
BASE_POINTS = {
    "rfq_request": 45,          # high positive — explicit buying request
    "interested": 30,           # positive — sales-qualified signal
    "technical_question": 18,   # medium positive — engagement / evaluation
    "price_request": 18,        # medium positive — evaluation / comparison
    # Neutral (no direct buying-intent signal): left at 0 so they neither
    # help nor hurt the score.
    "supplier_existing": 0,
    "out_of_office": 0,
    "not_now": 0,
    "wrong_contact": 0,
    "unknown": 0,
    # Negative — disinterest / noise.
    "not_interested": -30,
    "spam": -35,
}

# Engagement telemetry contributions (no confidence weighting; recency only).
EVENT_POINTS = {
    "opened": 5,    # weak positive interest
    "bounced": -10,  # negative — deliverability
}

SCORE_FLOOR = -100
SCORE_CEIL = 100

METHOD_VERSION = "deterministic_v1"


# ---------------------------------------------------------------------------
# Pure scoring helpers (no DB)
# ---------------------------------------------------------------------------
def recency_decay(age_days: float, half_life: float = HALF_LIFE_DAYS) -> float:
    """Exponential half-life decay factor for a reply/event age in days."""
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life)


def score_reply(
    intent: str,
    confidence: Optional[float],
    age_days: float,
    half_life: float = HALF_LIFE_DAYS,
) -> float:
    """Weighted contribution of a single classified reply (deterministic)."""
    base = BASE_POINTS.get(intent, 0)
    if base == 0:
        return 0.0
    conf = 0.0 if confidence is None else max(0.0, min(1.0, float(confidence) / 100.0))
    return base * conf * recency_decay(age_days, half_life)


def score_event(
    event_type: str,
    age_days: float,
    half_life: float = HALF_LIFE_DAYS,
) -> float:
    """Weighted contribution of a single engagement telemetry event."""
    base = EVENT_POINTS.get(event_type, 0)
    if base == 0:
        return 0.0
    return base * recency_decay(age_days, half_life)


@dataclass
class IntentScoreResult:
    """Computed intent score + provenance (no persistence)."""

    intent_score: int
    dominant_intent: Optional[str]
    signal_sources: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "intent_score": self.intent_score,
            "dominant_intent": self.dominant_intent,
            "signal_sources": self.signal_sources,
        }


# ---------------------------------------------------------------------------
# DB-backed computation
# ---------------------------------------------------------------------------
def _age_days(dt: Optional[datetime], now: datetime) -> float:
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (now - dt).total_seconds() / 86400.0
    return max(0.0, delta)


def compute_intent_score(
    db: Session, lead_id: int, *, now: Optional[datetime] = None
) -> IntentScoreResult:
    """Compute the deterministic intent score for ``lead_id`` from the DB.

    Reads all :class:`ReplyAnalysis` and :class:`OutreachEvent` rows for the
    lead, applies confidence + recency weighting, and returns the result. Does
    **not** persist anything (see :class:`app.conversion.service.ConversionService`).
    """
    now = now or datetime.now(timezone.utc)

    analyses = (
        db.query(ReplyAnalysis)
        .filter(ReplyAnalysis.lead_id == lead_id)
        .all()
    )
    events = (
        db.query(OutreachEvent)
        .filter(OutreachEvent.lead_id == lead_id)
        .all()
    )

    total = 0.0
    # Per-intent accumulated absolute weighted contribution + latest timestamp.
    intent_weight: dict = {}
    intent_latest: dict = {}
    reply_sources: List[dict] = []

    for a in analyses:
        age = _age_days(a.created_at, now)
        weighted = score_reply(a.intent, a.confidence_score, age)
        total += weighted
        reply_sources.append(
            {
                "id": a.id,
                "intent": a.intent,
                "confidence": a.confidence_score,
                "age_days": round(age, 2),
                "weighted": round(weighted, 3),
            }
        )
        if a.intent in BASE_POINTS and BASE_POINTS.get(a.intent, 0) != 0:
            intent_weight[a.intent] = intent_weight.get(a.intent, 0.0) + abs(weighted)
            ts = a.created_at
            if ts is not None and (
                a.intent not in intent_latest or (intent_latest[a.intent] is None or ts > intent_latest[a.intent])
            ):
                intent_latest[a.intent] = ts

    event_sources: List[dict] = []
    for e in events:
        # Only classification-free engagement signals are scored here; the
        # analyzer already records a ReplyAnalysis for genuine replies, so we
        # must not double-count "replied".
        if e.event_type in EVENT_POINTS:
            age = _age_days(e.created_at, now)
            weighted = score_event(e.event_type, age)
            total += weighted
            event_sources.append(
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "age_days": round(age, 2),
                    "weighted": round(weighted, 3),
                }
            )

    intent_score = int(round(max(SCORE_FLOOR, min(SCORE_CEIL, total))))

    # Dominant intent = largest absolute accumulated weighted contribution.
    dominant_intent: Optional[str] = None
    if intent_weight:
        dominant_intent = max(
            intent_weight,
            key=lambda i: (intent_weight[i], intent_latest.get(i) or datetime.min.replace(tzinfo=timezone.utc)),
        )

    signal_sources = {
        "method": METHOD_VERSION,
        "half_life_days": HALF_LIFE_DAYS,
        "score_floor": SCORE_FLOOR,
        "score_ceiling": SCORE_CEIL,
        "raw_total": round(total, 3),
        "reply_analyses": reply_sources,
        "outreach_events": event_sources,
        "intent_weights": {k: round(v, 3) for k, v in intent_weight.items()},
        "computed_at": now.isoformat(),
    }

    return IntentScoreResult(
        intent_score=intent_score,
        dominant_intent=dominant_intent,
        signal_sources=signal_sources,
    )
