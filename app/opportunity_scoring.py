"""Opportunity scoring (Phase 11).

Deterministic baseline scoring of a deal (amount / probability / priority /
expected close date), with an optional LLM assist via
:func:`app.ai_sales_agent.llm.complete_json`.

The deterministic baseline always runs first and is the sole source of truth
when AI is disabled, the call fails, or returns nothing usable. When AI
contributes a usable value for a field it overrides the deterministic one. This
keeps pipeline analytics reproducible in tests and safe in production
regardless of provider availability — and, critically, never calls OpenAI
directly.
"""
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Tuple

from app.ai_sales_agent.llm import complete_json
from app.models.opportunity import (
    OPP_PRIORITY_MEDIUM,
    STAGE_PROBABILITY,
    default_probability,
)


# Keys produced by the scorer (stable for serialization / merging).
_SCORE_FIELDS = (
    "amount",
    "currency",
    "probability",
    "priority",
    "expected_close_date",
    "notes",
)

_DEADLINE_URGENT = (
    "asap", "urgent", "immediately", "soon", "this week", "next week",
    "end of month", "this month", "q1", "q2", "q3", "q4",
)


def _parse_amount(raw: str) -> Optional[float]:
    """Parse a loosely formatted money string into a float, or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # strip currency symbols / codes / thousands separators (keep . and ,)
    s = re.sub(r"[^\d.,]", "", s)
    s = s.replace(",", "")
    try:
        val = float(s)
    except ValueError:
        return None
    return val if val > 0 else None


def _parse_date(raw: str) -> Optional[date]:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # "in 3 months" style relative hints
    m = re.search(r"(\d+)\s*month", s, re.I)
    if m:
        return date.today() + timedelta(days=30 * int(m.group(1)))
    return None


def estimate_baseline(
    stage: str,
    *,
    reply_text: Optional[str] = None,
    rfq_fields: Optional[Dict[str, Optional[str]]] = None,
    company_priority: Optional[str] = None,
) -> Dict[str, object]:
    """Deterministic baseline score — no network, always safe to call.

    Probability comes from the stage baseline and is nudged up when the RFQ
    shows an urgent deadline or a concrete quantity. Amount is *not* guessed
    (left ``None``) — only a human or the AI enhancement fills it.
    """
    probability = default_probability(stage)
    rfq = rfq_fields or {}
    text = (reply_text or "").lower()

    if any(h in text or h in " ".join(str(v or "") for v in rfq.values()).lower()
           for h in _DEADLINE_URGENT):
        probability = min(100, probability + 10)
    if (rfq.get("quantity") or "").strip():
        probability = min(100, probability + 5)

    priority = company_priority or OPP_PRIORITY_MEDIUM

    return {
        "amount": None,
        "currency": None,
        "probability": probability,
        "priority": priority,
        "expected_close_date": None,
        "notes": None,
    }


def enhance_with_ai(
    reply_text: Optional[str],
    rfq_fields: Optional[Dict[str, Optional[str]]],
    company_name: Optional[str] = None,
) -> Tuple[Dict[str, object], bool]:
    """Optional AI enhancement. Returns ``(fields, used_ai)``.

    ``used_ai`` is ``True`` only when the AI path actually contributed a usable
    value. Never raises; on any failure returns the empty baseline + ``False``.
    """
    fields: Dict[str, object] = {k: None for k in _SCORE_FIELDS}
    used_ai = False

    rfq = rfq_fields or {}
    prompt_user = (
        f"Company: {company_name or 'unknown'}\n"
        f"Reply: {reply_text or ''}\n"
        f"Extracted RFQ: {rfq}\n\n"
        "Estimate deal parameters. Return JSON with keys: amount (number), "
        "currency (3-letter code), probability (integer 0-100), priority "
        "(high|medium|low), expected_close_date (YYYY-MM-DD), notes (short "
        "string). Use null for unknowns."
    )
    ai = complete_json(
        system=(
            "You are a B2B sales pipeline scoring assistant for a die-casting "
            "manufacturer. You estimate deal value and win probability from a "
            "customer RFQ reply. Respond ONLY with a JSON object."
        ),
        user=prompt_user,
        temperature=0.2,
        max_tokens=400,
    )
    if not isinstance(ai, dict):
        return fields, used_ai

    for key in _SCORE_FIELDS:
        val = ai.get(key)
        if val is None:
            continue
        if key == "amount":
            parsed = _parse_amount(val)
            if parsed is not None:
                fields["amount"] = parsed
                used_ai = True
        elif key == "currency":
            cv = str(val).strip().upper()
            if len(cv) == 3 and cv.isalpha():
                fields["currency"] = cv
                used_ai = True
        elif key == "probability":
            try:
                pv = int(float(val))
            except (TypeError, ValueError):
                pv = None
            if pv is not None and 0 <= pv <= 100:
                fields["probability"] = pv
                used_ai = True
        elif key == "priority":
            pv = str(val).strip().lower()
            if pv in ("high", "medium", "low"):
                fields["priority"] = pv
                used_ai = True
        elif key == "expected_close_date":
            d = _parse_date(val)
            if d is not None:
                fields["expected_close_date"] = d
                used_ai = True
        elif key == "notes":
            sv = str(val).strip()
            if sv:
                fields["notes"] = sv[:1000]
                used_ai = True

    return fields, used_ai


def score_opportunity(
    stage: str,
    *,
    reply_text: Optional[str] = None,
    rfq_fields: Optional[Dict[str, Optional[str]]] = None,
    company_priority: Optional[str] = None,
    company_name: Optional[str] = None,
    use_ai: bool = True,
) -> Tuple[Dict[str, object], bool]:
    """Compute the final score dict merging baseline + (optional) AI.

    Returns ``(score, used_ai)`` where ``used_ai`` reflects whether the AI path
    contributed. Baseline is authoritative for any field AI leaves empty.
    """
    score = estimate_baseline(
        stage,
        reply_text=reply_text,
        rfq_fields=rfq_fields,
        company_priority=company_priority,
    )
    used_ai = False
    if use_ai:
        ai_fields, ai_used = enhance_with_ai(reply_text, rfq_fields, company_name)
        for key in _SCORE_FIELDS:
            if ai_fields.get(key) is not None:
                score[key] = ai_fields[key]
        used_ai = ai_used
    # probability is always defined (baseline guarantees it).
    if score.get("probability") is None:
        score["probability"] = default_probability(stage)
    return score, used_ai
