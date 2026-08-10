"""Deterministic next-action recommendation engine (Phase 15.1.4).

Turns a lead's existing conversion-intelligence snapshot (dominant intent,
intent score, temperature) into a single recommended **next action** plus a
priority and a human-readable reason. No LLM, no network, fully deterministic.

Decision tree (highest precedence first):

* ``spam``                 -> ``suppress_contact``   (high)  protect sender rep
* ``not_interested``       -> ``stop_sequence``      (high)  honour opt-out
* ``rfq_request``          -> ``prepare_quote``      (hot/warm high|medium; cold medium)
* ``technical_question``   -> ``engineering_response`` (priority by temperature)
* ``interested``           -> ``send_capability_case`` (priority by temperature)
* ``price_request``        -> ``send_capability_case`` (evaluation signal; by temp)
* no strong positive intent (unknown / not_now / out_of_office /
  supplier_existing / wrong_contact / None):
    - warm / hot  -> ``follow_up_sequence``   (the "no response + warm" rule)
    - cold        -> ``monitor``              (low)  low-priority nurture watch

Priority is always one of ``high`` / ``medium`` / ``low``.

Pure helpers (:func:`recommend_next_action`, :func:`priority_from_label`) are
exported so the decision logic can be unit-tested without a database.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.conversion import intent as intent_engine
from app.conversion import temperature as temperature_engine

# ---------------------------------------------------------------------------
# Action vocabulary
# ---------------------------------------------------------------------------
ACTION_PREPARE_QUOTE = "prepare_quote"
ACTION_ENGINEERING_RESPONSE = "engineering_response"
ACTION_SEND_CAPABILITY_CASE = "send_capability_case"
ACTION_FOLLOW_UP_SEQUENCE = "follow_up_sequence"
ACTION_STOP_SEQUENCE = "stop_sequence"
ACTION_SUPPRESS_CONTACT = "suppress_contact"
ACTION_MONITOR = "monitor"

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

METHOD_VERSION = "deterministic_v1"


# ---------------------------------------------------------------------------
# Pure decision logic (no DB)
# ---------------------------------------------------------------------------
def priority_from_label(label: Optional[str]) -> str:
    """Map a temperature label onto high/medium/low priority."""
    if label == "hot":
        return PRIORITY_HIGH
    if label == "warm":
        return PRIORITY_MEDIUM
    return PRIORITY_LOW  # cold or unknown


def recommend_next_action(
    dominant_intent: Optional[str],
    intent_score: Optional[int],
    temperature_score: Optional[int],
    temperature_label: Optional[str],
) -> "NextActionResult":
    """Deterministic next-action recommendation from a lead's signals.

    ``dominant_intent`` and ``intent_score`` describe the strongest buying /
    disinterest signal; ``temperature_score`` / ``temperature_label`` describe
    composite engagement heat. Returns the chosen action, its priority, and a
    human-readable reason string.
    """
    intent_score = intent_score if intent_score is not None else 0
    temperature_score = temperature_score if temperature_score is not None else 0
    temperature_label = temperature_label or "cold"

    # --- Safety / negative signals first ----------------------------------
    if dominant_intent == "spam":
        return NextActionResult(
            ACTION_SUPPRESS_CONTACT,
            PRIORITY_HIGH,
            "Spam signal detected: suppress further contact to protect sender "
            "reputation and deliverability.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )
    if dominant_intent == "not_interested":
        return NextActionResult(
            ACTION_STOP_SEQUENCE,
            PRIORITY_HIGH,
            "Explicit disinterest: stop the outreach sequence and honour the "
            "opt-out / do-not-contact state.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )

    # --- Strong buying signals -------------------------------------------
    if dominant_intent == "rfq_request":
        # Explicit quote request is always worth a quote, but a fresh/hot one is
        # the highest priority. A stale (cold) RFQ is re-engaged at medium.
        if temperature_label == "hot":
            priority = PRIORITY_HIGH
        elif temperature_label == "warm":
            priority = PRIORITY_HIGH
        else:  # cold (decayed / stale RFQ)
            priority = PRIORITY_MEDIUM
        return NextActionResult(
            ACTION_PREPARE_QUOTE,
            priority,
            f"RFQ request (intent_score={intent_score}, "
            f"temperature={temperature_score}/{temperature_label}): prepare and "
            f"send a tailored quotation.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )

    # --- Evaluation / engagement signals ---------------------------------
    if dominant_intent == "technical_question":
        priority = priority_from_label(temperature_label)
        return NextActionResult(
            ACTION_ENGINEERING_RESPONSE,
            priority,
            f"Technical inquiry (temperature={temperature_score}/"
            f"{temperature_label}): route to engineering for a technical "
            f"response.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )
    if dominant_intent in ("interested", "price_request"):
        # Both are positive evaluation signals best served by a capability /
        # value case (pricing questions included).
        priority = priority_from_label(temperature_label)
        action_label = "interest" if dominant_intent == "interested" else "price inquiry"
        return NextActionResult(
            ACTION_SEND_CAPABILITY_CASE,
            priority,
            f"Positive {action_label} (temperature={temperature_score}/"
            f"{temperature_label}): send a targeted capability / value case.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )

    # --- No strong positive intent (unknown / not_now / out_of_office / ...)
    if temperature_label in ("hot", "warm"):
        # "No response + warm" (or weak-signal warm): keep the sequence alive.
        priority = PRIORITY_MEDIUM if temperature_label == "warm" else PRIORITY_HIGH
        return NextActionResult(
            ACTION_FOLLOW_UP_SEQUENCE,
            priority,
            f"No strong buying intent but warm engagement "
            f"(temperature={temperature_score}/{temperature_label}): continue a "
            f"follow-up sequence.",
            dominant_intent, intent_score, temperature_score, temperature_label,
        )

    # Cold / no signal -> low-priority monitor.
    return NextActionResult(
        ACTION_MONITOR,
        PRIORITY_LOW,
        f"No positive intent and cold engagement "
        f"(temperature={temperature_score}/{temperature_label}): monitor with "
        f"low-priority nurture, no immediate action.",
        dominant_intent, intent_score, temperature_score, temperature_label,
    )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class NextActionResult:
    """Recommended next action + priority + reason (no persistence)."""

    next_action: str
    next_action_priority: str
    next_action_reason: str
    # Surfaced signals used to derive the action (so the caller can persist a
    # consistent row without a second pass).
    dominant_intent: Optional[str] = None
    intent_score: Optional[int] = None
    temperature_score: Optional[int] = None
    temperature_label: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "next_action": self.next_action,
            "next_action_priority": self.next_action_priority,
            "next_action_reason": self.next_action_reason,
            "dominant_intent": self.dominant_intent,
            "intent_score": self.intent_score,
            "temperature_score": self.temperature_score,
            "temperature_label": self.temperature_label,
        }


# ---------------------------------------------------------------------------
# DB-backed computation
# ---------------------------------------------------------------------------
def compute_next_action(
    db: Session,
    lead_id: int,
    *,
    now: Optional[object] = None,
    dominant_intent: Optional[str] = None,
    intent_score: Optional[int] = None,
    temperature_score: Optional[int] = None,
    temperature_label: Optional[str] = None,
) -> NextActionResult:
    """Compute the deterministic next action for ``lead_id`` from the DB.

    Reads the lead's intent and temperature signals (recomputing them
    deterministically from the same underlying data when not supplied) and
    returns the recommendation. Does **not** persist anything (see
    :class:`app.conversion.service.ConversionService`).

    Passing the signals explicitly (e.g. from an already-populated
    :class:`ConversionSignal` row) skips the recompute and is useful for testing.
    """
    if dominant_intent is None or intent_score is None:
        intent_result = intent_engine.compute_intent_score(db, lead_id, now=now)
        if dominant_intent is None:
            dominant_intent = intent_result.dominant_intent
        if intent_score is None:
            intent_score = intent_result.intent_score

    if temperature_score is None or temperature_label is None:
        temp = temperature_engine.compute_temperature(
            db, lead_id, now=now, intent_score=intent_score
        )
        if temperature_score is None:
            temperature_score = temp.temperature_score
        if temperature_label is None:
            temperature_label = temp.temperature_label

    result = recommend_next_action(
        dominant_intent, intent_score, temperature_score, temperature_label
    )
    # Surface the signals used so the caller can persist a consistent row.
    result.dominant_intent = dominant_intent
    result.intent_score = intent_score
    result.temperature_score = temperature_score
    result.temperature_label = temperature_label
    return result
