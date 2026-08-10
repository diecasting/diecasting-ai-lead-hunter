"""Conversion intelligence package (Phase 15.1).

A deterministic, offline-testable layer that turns existing reply
classification, RFQ extraction, and engagement telemetry into actionable
conversion signals (intent score, lead temperature, and later next-action).

Current scope (15.1.1 + 15.1.2 + 15.1.3):
  * ``intent``       — deterministic intent-score engine (ReplyAnalysis + OutreachEvent).
  * ``temperature``  — deterministic lead-temperature engine (intent + recency +
                       engagement + contact ranking -> 0..100 cold/warm/hot).
  * ``service``      — ``ConversionService`` compute/persist orchestration.

Later phases (not in this layer yet): next-action recommendation (15.1.4).
No LLM, no external APIs, no changes to the outreach send path / quality gate /
opportunity stages / campaign sending.
"""
from app.conversion.intent import (
    BASE_POINTS,
    EVENT_POINTS,
    HALF_LIFE_DAYS,
    IntentScoreResult,
    compute_intent_score,
    recency_decay,
    score_event,
    score_reply,
)
from app.conversion.temperature import (
    TemperatureResult,
    combine_temperature,
    compute_temperature,
    contact_component,
    engagement_component,
    intent_strength_component,
    label_for_score,
    recency_component,
)
from app.conversion.service import ConversionService

__all__ = [
    "ConversionService",
    "IntentScoreResult",
    "TemperatureResult",
    "compute_intent_score",
    "compute_temperature",
    "score_reply",
    "score_event",
    "recency_decay",
    "intent_strength_component",
    "recency_component",
    "engagement_component",
    "contact_component",
    "combine_temperature",
    "label_for_score",
    "BASE_POINTS",
    "EVENT_POINTS",
    "HALF_LIFE_DAYS",
]
