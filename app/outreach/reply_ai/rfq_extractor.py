"""RFQ extraction from a classified reply (Phase 10).

Deterministic, offline-testable extraction of quotation requirements
(product / quantity / material / process / deadline / free-form requirements)
with an optional LLM assist via :func:`app.ai_sales_agent.llm.complete_json`.

The deterministic parser always runs first and is the sole source of truth when
AI is disabled, the call fails, or returns nothing usable (``used_ai`` stays
``False``). When AI contributes a non-empty value for a field it overrides the
deterministic one. This keeps the pipeline reproducible in tests and safe in
production regardless of provider availability.
"""
import re
from typing import Dict, Optional, Tuple

from app.ai_sales_agent.llm import complete_json


# ---------------------------------------------------------------------------
# Deterministic keyword banks (matched against the lower-cased reply)
# ---------------------------------------------------------------------------
_MATERIALS = (
    ("aluminium", "Aluminium"),
    ("aluminum", "Aluminum"),
    ("adc12", "ADC12"),
    ("a380", "A380"),
    ("a360", "A360"),
    ("a383", "A383"),
    ("a356", "A356"),
    ("zl101", "ZL101"),
    ("zinc", "Zinc"),
    ("za8", "ZA8"),
    ("zamak", "Zamak"),
    ("magnesium", "Magnesium"),
    ("az91d", "AZ91D"),
    ("steel", "Steel"),
    ("stainless", "Stainless Steel"),
    ("brass", "Brass"),
)

_PROCESSES = (
    "die cast", "die casting", "die-cast", "die-casting",
    "cnc", "machining", "machined", "milling", "turning",
    "injection mold", "injection mould", "injection molding",
    "stamping", "forging",
)

_DEADLINE_HINTS = (
    "asap", "urgent", "immediately", "as soon as possible",
    "by end of month", "end of quarter", "next quarter", "next month",
    "this week", "next week", "this month", "q1", "q2", "q3", "q4",
)

# Fields the extractor produces (order is stable for serialization).
_FIELDS = ("product", "quantity", "material", "process", "deadline", "requirements")


def _find_materials(text: str) -> Optional[str]:
    found = []
    for key, label in _MATERIALS:
        if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", text):
            found.append(label)
    if not found:
        return None
    # de-duplicate while preserving order
    return ", ".join(dict.fromkeys(found))


def _find_process(text: str) -> Optional[str]:
    found = [p for p in _PROCESSES if p in text]
    if not found:
        return None
    return ", ".join(dict.fromkeys(found))


def _find_quantity(text: str) -> Optional[str]:
    patterns = [
        r"\d[\d,\.]*\s*(?:pcs|pieces|units|parts|k|kk)\b",
        r"\d[\d,\.]*\s*(?:k|thousand)\b",
        r"monthly[\s\w]*?(\d[\d,\.]*)",
        r"annual[\s\w]*?(\d[\d,\.]*)",
        r"\d[\d,\.]*\s*(?:per\s+month|per\s+year|/month|/year)",
        r"\b(\d[\d,\.]*)\s*(?:sets|lot|lots)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0).strip()
    return None


def _find_deadline(text: str) -> Optional[str]:
    for hint in _DEADLINE_HINTS:
        if hint in text:
            return hint
    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    if m:
        return m.group(0)
    return None


def _deterministic_extract(reply_text: str) -> Dict[str, Optional[str]]:
    t = (reply_text or "").lower()
    return {
        "product": None,
        "quantity": _find_quantity(t),
        "material": _find_materials(t),
        "process": _find_process(t),
        "deadline": _find_deadline(t),
        "requirements": (reply_text or "").strip()[:2000] or None,
    }


def extract_rfq(
    reply_text: str, *, use_ai: bool = True
) -> Tuple[Dict[str, Optional[str]], bool]:
    """Return ``(fields, used_ai)``.

    Always runs the deterministic parser first; when ``use_ai`` is true and the
    LLM returns a dict, AI values override the deterministic ones (non-empty
    only). ``used_ai`` is ``True`` only when the AI path actually contributed a
    usable value.
    """
    fields = _deterministic_extract(reply_text)
    used_ai = False

    if use_ai:
        ai = complete_json(
            system=(
                "You extract RFQ (request-for-quote) requirements from a "
                "customer email. Return a JSON object with exactly these keys: "
                "product, quantity, material, process, deadline, requirements. "
                "Use short strings; omit unknown fields as empty strings."
            ),
            user=reply_text or "",
            temperature=0.2,
            max_tokens=400,
        )
        if isinstance(ai, dict):
            contributed = False
            for key in _FIELDS:
                val = (ai.get(key) or "").strip()
                if val:
                    fields[key] = val
                    contributed = True
            used_ai = contributed

    return fields, used_ai
