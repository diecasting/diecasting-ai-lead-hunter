"""Conversion intelligence package (Phase 15.1).

A deterministic, offline-testable layer that turns existing reply
classification, RFQ extraction, and engagement telemetry into actionable
conversion signals (intent score, lead temperature, and later next-action).

Current scope (15.1.1 + 15.1.2 + 15.1.3 + 15.1.4):
  * ``intent``       — deterministic intent-score engine (ReplyAnalysis + OutreachEvent).
  * ``temperature``  — deterministic lead-temperature engine (intent + recency +
                       engagement + contact ranking -> 0..100 cold/warm/hot).
  * ``action``       — deterministic next-action recommender (dominant intent +
                       intent score + temperature -> action / priority / reason).
  * ``service``      — ``ConversionService`` compute/persist orchestration.

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
from app.conversion.action import (
    ACTION_ENGINEERING_RESPONSE,
    ACTION_FOLLOW_UP_SEQUENCE,
    ACTION_MONITOR,
    ACTION_PREPARE_QUOTE,
    ACTION_SEND_CAPABILITY_CASE,
    ACTION_STOP_SEQUENCE,
    ACTION_SUPPRESS_CONTACT,
    NextActionResult,
    compute_next_action,
    priority_from_label,
    recommend_next_action,
)
from app.conversion.service import ConversionService
from app.conversion.execution import (
    SUPPORTED_ACTIONS,
    create_task_from_recommendation,
    mark_recommendation_completed,
    expire_stale_recommendations,
)

__all__ = [
    "ConversionService",
    "create_task_from_recommendation",
    "mark_recommendation_completed",
    "expire_stale_recommendations",
    "SUPPORTED_ACTIONS",
    "IntentScoreResult",
    "TemperatureResult",
    "NextActionResult",
    "compute_intent_score",
    "compute_temperature",
    "compute_next_action",
    "recommend_next_action",
    "priority_from_label",
    "score_reply",
    "score_event",
    "recency_decay",
    "intent_strength_component",
    "recency_component",
    "engagement_component",
    "contact_component",
    "combine_temperature",
    "label_for_score",
    "ACTION_PREPARE_QUOTE",
    "ACTION_ENGINEERING_RESPONSE",
    "ACTION_SEND_CAPABILITY_CASE",
    "ACTION_FOLLOW_UP_SEQUENCE",
    "ACTION_STOP_SEQUENCE",
    "ACTION_SUPPRESS_CONTACT",
    "ACTION_MONITOR",
    "BASE_POINTS",
    "EVENT_POINTS",
    "HALF_LIFE_DAYS",
]
