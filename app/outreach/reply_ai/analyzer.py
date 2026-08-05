"""Reply analysis pipeline (Phase 6 Stage 2).

:func:`analyze_reply` runs the classifier on a customer reply, persists a
:class:`ReplyAnalysis` row, applies the intent-driven CRM automation, and
records a ``replied`` timeline event (best-effort) for genuine customer
responses.
"""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis
from app.outreach.reply_ai import action as reply_action
from app.outreach.reply_ai.classifier import classify_reply

# Intents that count as a genuine customer response (timeline-worthy).
_REAL_REPLY_INTENTS = {
    "interested",
    "rfq_request",
    "technical_question",
    "price_request",
    "supplier_existing",
    "not_interested",
}


def analyze_reply(
    db: Session,
    lead: CompanyLead,
    *,
    reply_text: str,
    message_id: Optional[int] = None,
    apply_actions: bool = True,
) -> Tuple[ReplyAnalysis, List[str]]:
    """Classify a reply, persist the analysis, and apply the CRM automation.

    Returns ``(analysis, applied_actions)`` where ``applied_actions`` is the
    list of CRM changes made (empty for intents without automation rules).
    """
    cls = classify_reply(reply_text)
    analysis = ReplyAnalysis(
        lead_id=lead.id,
        message_id=message_id,
        reply_text=(reply_text or "")[:5000],
        intent=cls.intent,
        confidence_score=cls.confidence,
        recommended_action=cls.recommended_action,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    actions: List[str] = []
    if apply_actions:
        actions = reply_action.apply_intent_action(db, lead, analysis)

    # Timeline: a genuine customer response is a 'replied' milestone.
    if cls.intent in _REAL_REPLY_INTENTS:
        try:
            from app.crud import outreach_events as events_crud

            events_crud.create(
                db, lead_id=lead.id, event_type="replied", message_id=message_id
            )
        except Exception:
            pass  # timeline recording is best-effort

    return analysis, actions


def list_analyses(
    db: Session, lead_id: int, *, limit: int = 50
) -> List[ReplyAnalysis]:
    """Return a lead's reply analyses, newest first."""
    return (
        db.query(ReplyAnalysis)
        .filter(ReplyAnalysis.lead_id == lead_id)
        .order_by(ReplyAnalysis.created_at.desc(), ReplyAnalysis.id.desc())
        .limit(limit)
        .all()
    )
