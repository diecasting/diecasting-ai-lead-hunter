"""Rule-based reply intent classifier (Phase 6 Stage 2).

Deterministic, offline-testable intent detection for inbound customer replies.
Each intent has a keyword bank; the classifier scores every rule that matches
the lower-cased reply text and picks the highest-confidence intent. Confidence
grows with the number of matched keywords (capped) so the score is
reproducible in tests and production alike.
"""
from dataclasses import dataclass
from typing import List, Tuple

# Canonical intent categories (order = tie-break priority).
INTENTS: List[str] = [
    "interested",
    "rfq_request",
    "technical_question",
    "price_request",
    "supplier_existing",
    "not_interested",
    "out_of_office",
    "unknown",
    # --- Phase 10 additions (appended so they lose ties to the sales-critical
    #     intents above: a reply is only tagged wrong_contact / not_now / spam
    #     when no stronger intent matches) ---
    "wrong_contact",
    "not_now",
    "spam",
]

# (intent, keyword bank, recommended_action). Matching is case-insensitive
# substring matching against the whole reply text; keep entries lower-case.
_RULES: List[Tuple[str, Tuple[str, ...], str]] = [
    (
        "out_of_office",
        (
            "out of office",
            "out-of-office",
            "auto reply",
            "auto-reply",
            "annual leave",
            "on vacation",
            "on holiday",
            "away from the office",
            "will be back",
            "currently unavailable",
            "unable to respond",
        ),
        "no action; re-engage after the absence",
    ),
    (
        "not_interested",
        (
            "not interested",
            "no thanks",
            "no thank you",
            "please unsubscribe",
            "stop sending",
            "stop emailing",
            "don't contact",
            "do not contact",
            "remove me",
            "not looking",
            "this is spam",
            "take me off",
        ),
        "stop follow-ups; mark do-not-contact",
    ),
    (
        "supplier_existing",
        (
            "already have a supplier",
            "existing supplier",
            "current supplier",
            "already work with",
            "happy with our supplier",
            "satisfied with our supplier",
            "supplier in place",
            "have a vendor",
            "already have a vendor",
            "we have a supplier",
        ),
        "stop follow-up sequence; log existing supplier",
    ),
    (
        "price_request",
        (
            "price list",
            "your pricing",
            "pricing for",
            "how much",
            "unit price",
            "price for",
            "cost per",
            "price quote",
            "what are your prices",
            "quote me a price",
            "price of",
        ),
        "respond with pricing; no status change",
    ),
    (
        "rfq_request",
        (
            "rfq",
            "request for quotation",
            "request for quote",
            "request a quote",
            "please quote",
            "send us a quote",
            "send me a quote",
            "send quotation",
            "submit a quotation",
            "submit a quote",
            "we need a quote",
            "quote for",
            "quotation for",
            "quote needed",
        ),
        "move lead to rfq; prepare quotation",
    ),
    (
        "technical_question",
        (
            "tolerance",
            "specification",
            "specs",
            "material grade",
            "surface finish",
            "certification",
            "iso 9001",
            "iatf",
            "quality standard",
            "test report",
            "mechanical property",
            "drawing",
            "drawings",
            "cad file",
            "thread",
            "can you machine",
            "do you cast",
            "technical question",
            "material certificate",
        ),
        "answer technical questions; no status change",
    ),
    (
        "interested",
        (
            "very interested",
            "we are interested",
            "we're interested",
            "i am interested",
            "i'm interested",
            "interested in",
            "sounds good",
            "looks promising",
            "please send more information",
            "tell me more",
            "more details",
            "schedule a call",
            "book a call",
            "set up a call",
            "let's talk",
            "lets talk",
            "arrange a meeting",
            "schedule a meeting",
            "look forward to",
            "great fit",
            "we would like",
            "we'd like",
        ),
        "move lead to qualified; continue outreach",
    ),
    (
        "wrong_contact",
        (
            "wrong person",
            "wrong contact",
            "not the right person",
            "not my department",
            "you have the wrong",
            "incorrect contact",
            "reach out to",
            "please contact",
            "forward this to",
            "wrong email",
            "not with this company",
            "no longer with",
            "left the company",
            "try contacting",
        ),
        "route to correct contact; flag data quality",
    ),
    (
        "not_now",
        (
            "not now",
            "not right now",
            "maybe later",
            "some other time",
            "in the future",
            "down the line",
            "circle back",
            "touch base later",
            "not a priority",
            "no budget",
            "budget later",
            "next quarter",
            "next year",
            "currently not",
            "not ready",
            "we are not ready",
            "right now we are",
        ),
        "re-engage after a delay; nurture",
    ),
    (
        "spam",
        (
            "spam",
            "delete this",
            "remove from",
            "report as spam",
            "viagra",
            "crypto",
            "lottery",
            "winner",
            "click here to claim",
            "make money fast",
            "free gift",
            "congratulations you",
            "loan offer",
            "investment opportunity",
            "casino",
            "claim your prize",
        ),
        "flag as spam; do not engage",
    ),
]


@dataclass(frozen=True)
class ReplyClassification:
    """Result of classifying a customer reply."""

    intent: str
    confidence: float  # 0-100
    recommended_action: str

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
        }


def classify_reply(text: str) -> ReplyClassification:
    """Classify ``text`` into one of the intent categories.

    Deterministic: the highest-confidence matching rule wins; ties break in
    ``INTENTS`` priority order. No matches -> ``unknown`` with low confidence.
    """
    t = (text or "").lower()
    scores: dict = {}
    for intent, keywords, action in _RULES:
        hits = [k for k in keywords if k in t]
        if hits:
            confidence = 55.0 + 12.0 * len(hits)
            if len(hits) >= 2:
                confidence += 10.0
            scores[intent] = (min(confidence, 98.0), action, len(hits))

    if not scores:
        return ReplyClassification(
            intent="unknown",
            confidence=35.0,
            recommended_action="manual review",
        )

    best = max(scores, key=lambda i: (scores[i][0], -INTENTS.index(i)))
    confidence, action, _hits = scores[best]
    return ReplyClassification(
        intent=best,
        confidence=round(confidence, 1),
        recommended_action=action,
    )
