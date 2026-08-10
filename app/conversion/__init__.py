"""Conversion intelligence package (Phase 15.1).

A deterministic, offline-testable layer that turns existing reply
classification, RFQ extraction, and engagement telemetry into actionable
conversion signals (intent score, and later temperature + next-action).

Current scope (15.1.1 + 15.1.2):
  * ``intent``  — deterministic intent-score engine (ReplyAnalysis + OutreachEvent).
  * ``service`` — ``ConversionService`` compute/persist orchestration.

Later phases (not in this layer yet): temperature scoring (15.1.3) and
next-action recommendation (15.1.4). No LLM, no external APIs, no changes to
the outreach send path / quality gate / opportunity stages / campaign sending.
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
from app.conversion.service import ConversionService

__all__ = [
    "ConversionService",
    "IntentScoreResult",
    "compute_intent_score",
    "score_reply",
    "score_event",
    "recency_decay",
    "BASE_POINTS",
    "EVENT_POINTS",
    "HALF_LIFE_DAYS",
]
