"""AI Reply Intelligence Engine (Phase 6 Stage 2).

Package layout:

* ``classifier`` — rule-based intent classification of a customer reply
  (interested / rfq_request / technical_question / price_request /
  supplier_existing / not_interested / out_of_office / unknown /
  wrong_contact / not_now / spam — the last three added in Phase 10) with a
  confidence score and a recommended CRM action.
* ``action``     — CRM automation triggered by the detected intent (lead
  status transitions, follow-up / sequence cancellation).
* ``analyzer``   — end-to-end pipeline: classify → persist a
  :class:`ReplyAnalysis` → apply the CRM automation.
"""
from app.outreach.reply_ai.classifier import (
    INTENTS,
    ReplyClassification,
    classify_reply,
)
from app.outreach.reply_ai.analyzer import analyze_reply, list_analyses

__all__ = [
    "INTENTS",
    "ReplyClassification",
    "classify_reply",
    "analyze_reply",
    "list_analyses",
]
