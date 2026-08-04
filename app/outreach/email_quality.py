"""Outreach email quality scoring (Phase 4 Stage 2).

Scores a generated outreach email on three 0–100 axes so the pipeline (and the
human reviewer) can judge whether a draft is worth sending without reading it
line by line:

  * ``personalization_score`` — how tailored the email is to *this* prospect:
    uses the company name, the prospect's materials / process / industry, and
    the recipient's role. Generic "Dear Sir/Madam" / "your company" copy scores
    low.
  * ``relevance_score`` — how well the email's content matches the prospect's
    actual signals (materials, process, procurement type, products). A cold
    email that never references what the company actually makes scores low.
  * ``spam_risk_score`` — likelihood the message trips spam filters / reads as
    a mass blast: ALL-CAPS, excessive hype words, too many links / exclamation
    marks, missing personalization, or classic spam phrases. Higher = riskier.

All three are pure functions of (email_text, context) and fully deterministic,
so they are trivially unit-testable and can gate drafts in CI / the CRM.
"""
import re
from typing import Optional

from app.outreach.context import CustomerContext

# Hype / spam-trigger phrases that hurt deliverability and read as a mass blast.
_SPAM_PHRASES = {
    "free", "buy now", "act now", "limited time", "urgent", "guaranteed",
    "100%", "no obligation", "risk free", "click here", "order now",
    "best price", "cheap", "discount", "promo", "winner", "congratulations",
    "make money", "lowest price", "while supplies last", "don't miss",
}

# Generic placeholders that indicate NOT-personalised copy.
_GENERIC_MARKERS = {"your company", "dear sir", "dear madam", "to whom it may"}


def _count(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, re.IGNORECASE))


def personalization_score(email: str, context: Optional[CustomerContext] = None) -> int:
    """0–100: how tailored the email is to this prospect.

    Starts at 0 and earns points for: greeting the company by name, referencing
    the prospect's materials / process / industry / role, and avoiding generic
    placeholders. Caps at 100.
    """
    if not email:
        return 0
    lowered = email.lower()
    score = 0

    # Company name present (and not the placeholder "your company").
    company = (context.company or "").strip() if context else ""
    if company and company.lower() not in ("your company", ""):
        if company.lower() in lowered:
            score += 35
    # Penalise generic placeholder copy.
    if "your company" in lowered:
        score -= 20
    if any(m in lowered for m in _GENERIC_MARKERS):
        score -= 15

    # Reference to prospect signals (materials / process / industry / role).
    if context is not None:
        hits = 0
        for token in (
            context.materials,
            context.manufacturing_process,
            context.industry,
            context.contact_role,
        ):
            token = (token or "").strip().lower()
            if token and len(token) > 2 and token in lowered:
                hits += 1
        score += min(45, hits * 15)

    # Role-specific address boosts personalization.
    if context is not None and context.contact_role and context.contact_role.lower() in lowered:
        score += 10

    return max(0, min(100, score))


def relevance_score(email: str, context: Optional[CustomerContext] = None) -> int:
    """0–100: how well the email content matches the prospect's real signals.

    Rewards explicit mention of the prospect's materials, manufacturing process,
    industry, and procurement focus; rewards a concrete (non-generic) call to
    action. Caps at 100.
    """
    if not email:
        return 0
    lowered = email.lower()
    score = 0

    if context is None:
        # Without context we can only reward non-generic, substantive copy.
        return 50 if len(email.split()) >= 30 else 25

    # Materials / process / industry / procurement type mentions.
    tokens = []
    if context.materials:
        tokens += [t.strip().lower() for t in context.materials.split(",") if t.strip()]
    if context.manufacturing_process:
        tokens += [t.strip().lower() for t in context.manufacturing_process.split(",") if t.strip()]
    if context.industry:
        tokens += [context.industry.strip().lower()]
    if context.procurement_type:
        tokens += [context.procurement_type.strip().lower()]

    matched = 0
    for t in tokens:
        if len(t) > 2 and t in lowered:
            matched += 1
    if tokens:
        score += min(60, int(60 * matched / len(tokens)))

    # Concrete CTA (contains a question or "call") reads as relevant outreach.
    if "?" in email or "call" in lowered:
        score += 15

    # Generic fallback body with no real signal -> low.
    if "your company" in lowered and matched == 0:
        score = min(score, 20)

    return max(0, min(100, score))


def spam_risk_score(email: str, context: Optional[CustomerContext] = None) -> int:
    """0–100: higher = more likely to be flagged as spam / mass blast.

    Triggers: ALL-CAPS words, excessive '!', spam phrases, too many links,
    missing personalization, and very short / very long messages.
    """
    if not email:
        return 100  # empty email is useless -> maximal risk
    lowered = email.lower()
    risk = 0

    # Spam phrases.
    phrase_hits = sum(1 for p in _SPAM_PHRASES if p in lowered)
    risk += min(40, phrase_hits * 10)

    # ALL-CAPS words (>= 3 letters), a classic spam signal.
    caps_words = re.findall(r"\b[A-Z]{3,}\b", email)
    risk += min(20, len(caps_words) * 4)

    # Exclamation marks.
    risk += min(15, _count(email, r"!") * 5)

    # Links.
    links = _count(email, r"https?://")
    risk += min(15, links * 7)

    # Missing personalization -> mass-blast feel.
    company = (context.company or "").strip().lower() if context else ""
    if company and company not in ("your company", "") and company not in lowered:
        risk += 15
    if "your company" in lowered:
        risk += 10

    # Extreme length (very short or very long) mildly risky.
    words = len(email.split())
    if words < 20:
        risk += 10
    elif words > 400:
        risk += 5

    return max(0, min(100, risk))


def score_email_quality(
    email: str, context: Optional[CustomerContext] = None
) -> dict:
    """Return all three scores plus a simple ``quality`` summary.

    ``quality`` is a 0–100 overall score that rewards personalization +
    relevance and penalises spam risk.
    """
    pers = personalization_score(email, context)
    rel = relevance_score(email, context)
    spam = spam_risk_score(email, context)
    quality = max(0, min(100, int(pers * 0.4 + rel * 0.4 + (100 - spam) * 0.2)))
    return {
        "personalization_score": pers,
        "relevance_score": rel,
        "spam_risk_score": spam,
        "quality": quality,
    }
