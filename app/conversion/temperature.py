"""Deterministic lead-temperature engine (Phase 15.1.3).

Synthesises a single **lead temperature** (``0``..``100``) with a
``cold`` / ``warm`` / ``hot`` label from four independent, deterministically
weighted signals:

* **Intent strength (40%)** — derived from the already-computed
  :mod:`app.conversion.intent` score (which itself is confidence-weighted, so
  :class:`ReplyAnalysis` confidence is consumed transitively here).
* **Recency / activity (25%)** — half-life decay of the most recent activity
  timestamp (latest reply, outreach event, or ``CompanyLead.last_activity_time``).
* **Engagement (20%)** — :class:`OutreachEvent` telemetry (opens / replies push
  up, bounces push down).
* **Contact quality ranking (15%)** — best available ``Contact.ranking_score``
  (Phase 14.1); ``0`` when no ranked contact exists.

Temperature is a *composite heat* measure, complementary to the signed
``intent_score``: a lead with no activity at all scores ``0`` (cold), while a
recent, high-intent, well-engaged, well-ranked lead approaches ``100`` (hot).

Design rules (strictly deterministic — no LLM, no network):

* Every component is reduced to ``0..100`` before weighting, so the final score
  is always a clean ``0..100`` value.
* ``intent_strength`` maps the signed ``intent_score`` (``-100..100``) through a
  linear ``(intent_score + 100) / 2`` transform, so a strongly negative (spam /
  not-interested) lead reads cold and a strongly positive (rfq) lead reads hot.
* The final score is rounded to an integer and clamped to ``[0, 100]``.

Pure helpers (:func:`intent_strength_component`, :func:`recency_component`,
:func:`engagement_component`, :func:`contact_component`,
:func:`combine_temperature`, :func:`label_for_score`) are exported for offline
unit testing of the math without a database.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.conversion import intent as intent_engine
from app.models.contact import Contact
from app.models.lead import CompanyLead
from app.models.outreach_event import OutreachEvent
from app.models.reply_analysis import ReplyAnalysis

# ---------------------------------------------------------------------------
# Component weights (sum == 1.0)
# ---------------------------------------------------------------------------
INTENT_WEIGHT = 0.40
RECENCY_WEIGHT = 0.25
ENGAGEMENT_WEIGHT = 0.20
CONTACT_WEIGHT = 0.15

TEMP_FLOOR = 0
TEMP_CEIL = 100

# Recency half-life (days) for the activity axis.
RECENCY_HALF_LIFE_DAYS = 30

# Engagement telemetry unit contributions (count-based, recency-free).
# A genuine reply is the strongest engagement; a bounce is a net negative.
ENGAGEMENT_UNIT = {
    "opened": 1,
    "replied": 2,
    "bounced": -3,
    # outbound / lifecycle events carry no inbound engagement signal.
    "generated": 0,
    "approved": 0,
    "sent": 0,
}
# Points awarded per accumulated engagement unit (capped at 100).
ENGAGEMENT_UNIT_POINTS = 10

METHOD_VERSION = "deterministic_v1"

LABEL_COLD = "cold"
LABEL_WARM = "warm"
LABEL_HOT = "hot"


# ---------------------------------------------------------------------------
# Pure component helpers (no DB)
# ---------------------------------------------------------------------------
def intent_strength_component(intent_score: Optional[int]) -> float:
    """Map the signed intent score (-100..100) onto 0..100 intent strength."""
    if intent_score is None:
        return 0.0
    # Linear transform: -100 -> 0 (cold), 0 -> 50 (neutral), 100 -> 100 (hot).
    raw = (float(intent_score) + 100.0) / 2.0
    return max(TEMP_FLOOR, min(TEMP_CEIL, raw))


def recency_component(age_days: float, half_life: float = RECENCY_HALF_LIFE_DAYS) -> float:
    """Activity recency as 0..100 (fresh activity -> 100, decays with age)."""
    if age_days is None or age_days < 0:
        return 0.0
    # Mirrors intent recency decay; 100% at age 0, 50% at one half-life, etc.
    return max(TEMP_FLOOR, min(TEMP_CEIL, 100.0 * intent_engine.recency_decay(age_days, half_life)))


def engagement_component(units: float) -> float:
    """Map accumulated engagement units onto 0..100 engagement strength."""
    return max(TEMP_FLOOR, min(TEMP_CEIL, float(units) * ENGAGEMENT_UNIT_POINTS))


def contact_component(ranking_score: Optional[int]) -> float:
    """Best contact ranking score as 0..100 contact-quality strength."""
    if ranking_score is None:
        return 0.0
    return max(TEMP_FLOOR, min(TEMP_CEIL, float(ranking_score)))


def combine_temperature(
    intent_strength: float,
    recency: float,
    engagement: float,
    contact: float,
) -> int:
    """Weighted, clamped, rounded 0..100 composite temperature score."""
    combined = (
        intent_strength * INTENT_WEIGHT
        + recency * RECENCY_WEIGHT
        + engagement * ENGAGEMENT_WEIGHT
        + contact * CONTACT_WEIGHT
    )
    return int(round(max(TEMP_FLOOR, min(TEMP_CEIL, combined))))


def label_for_score(score: int) -> str:
    """Map a temperature score onto cold / warm / hot."""
    if score <= 30:
        return LABEL_COLD
    if score <= 70:
        return LABEL_WARM
    return LABEL_HOT


def _build_reason(
    intent_score: Optional[int],
    intent_strength: float,
    age_days: float,
    recency: float,
    engagement_units: float,
    engagement: float,
    ranking_score: Optional[int],
    contact: float,
    temperature: int,
    label: str,
) -> str:
    """Human-readable breakdown of the temperature computation."""
    return (
        f"intent_score={intent_score} -> strength {intent_strength:.1f} "
        f"({INTENT_WEIGHT:.2f}); "
        f"age_days={age_days:.1f} -> recency {recency:.1f} "
        f"({RECENCY_WEIGHT:.2f}); "
        f"engagement_units={engagement_units:.1f} -> engagement {engagement:.1f} "
        f"({ENGAGEMENT_WEIGHT:.2f}); "
        f"contact_ranking={ranking_score} -> quality {contact:.1f} "
        f"({CONTACT_WEIGHT:.2f}); "
        f"=> temperature {temperature} ({label})"
    )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class TemperatureResult:
    """Computed temperature + provenance (no persistence)."""

    temperature_score: int
    temperature_label: str
    temperature_reason: str
    components: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "temperature_score": self.temperature_score,
            "temperature_label": self.temperature_label,
            "temperature_reason": self.temperature_reason,
            "components": self.components,
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


def compute_temperature(
    db: Session,
    lead_id: int,
    *,
    now: Optional[datetime] = None,
    intent_score: Optional[int] = None,
) -> TemperatureResult:
    """Compute the deterministic lead temperature for ``lead_id`` from the DB.

    Reads the lead, its :class:`ReplyAnalysis`, :class:`OutreachEvent`, and
    ranked :class:`Contact` rows, derives the four components, and returns the
    composite. Does **not** persist anything (see
    :class:`app.conversion.service.ConversionService`).

    ``intent_score`` may be supplied to avoid recomputing intent; when omitted
    it is recomputed deterministically from the same data the intent engine
    uses, so temperature never depends on a prior intent pass having run.
    """
    now = now or datetime.now(timezone.utc)

    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()

    # --- Intent strength ---------------------------------------------------
    if intent_score is None:
        intent_score = intent_engine.compute_intent_score(db, lead_id).intent_score
    intent_strength = intent_strength_component(intent_score)

    # --- Recency / activity ------------------------------------------------
    latest_activity: Optional[datetime] = None
    if lead is not None and lead.last_activity_time is not None:
        latest_activity = lead.last_activity_time

    reply_ts = (
        db.query(ReplyAnalysis.created_at)
        .filter(ReplyAnalysis.lead_id == lead_id)
        .order_by(ReplyAnalysis.created_at.desc())
        .first()
    )
    if reply_ts is not None and reply_ts[0] is not None:
        if latest_activity is None or reply_ts[0] > latest_activity:
            latest_activity = reply_ts[0]

    event_ts = (
        db.query(OutreachEvent.created_at)
        .filter(OutreachEvent.lead_id == lead_id)
        .order_by(OutreachEvent.created_at.desc())
        .first()
    )
    if event_ts is not None and event_ts[0] is not None:
        if latest_activity is None or event_ts[0] > latest_activity:
            latest_activity = event_ts[0]

    age_days = _age_days(latest_activity, now)
    recency = recency_component(age_days)

    # --- Engagement (OutreachEvent telemetry) ------------------------------
    events = (
        db.query(OutreachEvent)
        .filter(OutreachEvent.lead_id == lead_id)
        .all()
    )
    engagement_units = 0.0
    for e in events:
        engagement_units += ENGAGEMENT_UNIT.get(e.event_type, 0)
    engagement = engagement_component(engagement_units)

    # --- Contact quality ranking -------------------------------------------
    ranking_row = (
        db.query(Contact.ranking_score)
        .filter(
            Contact.lead_id == lead_id,
            Contact.ranking_score.isnot(None),
            Contact.do_not_contact.is_(False),
        )
        .order_by(Contact.ranking_score.desc())
        .first()
    )
    ranking_score: Optional[int] = ranking_row[0] if ranking_row is not None else None
    contact = contact_component(ranking_score)

    # --- Combine -----------------------------------------------------------
    temperature = combine_temperature(intent_strength, recency, engagement, contact)
    label = label_for_score(temperature)
    reason = _build_reason(
        intent_score=intent_score,
        intent_strength=intent_strength,
        age_days=age_days,
        recency=recency,
        engagement_units=engagement_units,
        engagement=engagement,
        ranking_score=ranking_score,
        contact=contact,
        temperature=temperature,
        label=label,
    )

    components = {
        "method": METHOD_VERSION,
        "weights": {
            "intent": INTENT_WEIGHT,
            "recency": RECENCY_WEIGHT,
            "engagement": ENGAGEMENT_WEIGHT,
            "contact": CONTACT_WEIGHT,
        },
        "intent_score": intent_score,
        "intent_strength": round(intent_strength, 3),
        "age_days": round(age_days, 3),
        "recency": round(recency, 3),
        "engagement_units": engagement_units,
        "engagement": round(engagement, 3),
        "contact_ranking": ranking_score,
        "contact": round(contact, 3),
        "recency_half_life_days": RECENCY_HALF_LIFE_DAYS,
        "computed_at": now.isoformat(),
    }

    return TemperatureResult(
        temperature_score=temperature,
        temperature_label=label,
        temperature_reason=reason,
        components=components,
    )
