"""Phase 15.1.4: Next-Action Recommendation Engine.

Deterministic, offline tests — no LLM, no network. Exercises the next-action
decision logic directly and through
:class:`app.conversion.service.ConversionService` against the in-memory SQLite
fixture.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.conversion import (
    ACTION_ENGINEERING_RESPONSE,
    ACTION_FOLLOW_UP_SEQUENCE,
    ACTION_MONITOR,
    ACTION_PREPARE_QUOTE,
    ACTION_SEND_CAPABILITY_CASE,
    ACTION_STOP_SEQUENCE,
    ACTION_SUPPRESS_CONTACT,
    ConversionService,
    priority_from_label,
    recommend_next_action,
)
from app.models.contact import Contact
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.outreach_event import OutreachEvent
from app.models.reply_analysis import ReplyAnalysis


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _add_reply(db, lead_id, intent, confidence, *, age_days=0, text="reply"):
    a = ReplyAnalysis(
        lead_id=lead_id,
        reply_text=text,
        intent=intent,
        confidence_score=confidence,
    )
    if age_days:
        a.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.add(a)
    db.commit()
    return a


def _add_event(db, lead_id, event_type, *, age_days=0):
    e = OutreachEvent(lead_id=lead_id, event_type=event_type)
    if age_days:
        e.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.add(e)
    db.commit()
    return e


def _add_contact(db, lead_id, ranking_score, *, do_not_contact=False):
    c = Contact(
        lead_id=lead_id,
        email=f"c{ranking_score}@example.com",
        ranking_score=ranking_score,
        do_not_contact=do_not_contact,
    )
    db.add(c)
    db.commit()
    return c


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------
def test_rfq_hot_prepare_quote_high():
    r = recommend_next_action("rfq_request", 90, 85, "hot")
    assert r.next_action == ACTION_PREPARE_QUOTE
    assert r.next_action_priority == "high"


def test_rfq_warm_still_prepare_quote():
    # warm RFQ is still a quote action (high priority).
    r = recommend_next_action("rfq_request", 60, 55, "warm")
    assert r.next_action == ACTION_PREPARE_QUOTE
    assert r.next_action_priority == "high"


def test_rfq_cold_is_medium():
    r = recommend_next_action("rfq_request", 10, 20, "cold")
    assert r.next_action == ACTION_PREPARE_QUOTE
    assert r.next_action_priority == "medium"


def test_technical_inquiry_engineering_response():
    r = recommend_next_action("technical_question", 18, 55, "warm")
    assert r.next_action == ACTION_ENGINEERING_RESPONSE
    assert r.next_action_priority == "medium"


def test_interested_capability_case():
    r = recommend_next_action("interested", 30, 60, "warm")
    assert r.next_action == ACTION_SEND_CAPABILITY_CASE
    assert r.next_action_priority == "medium"


def test_price_request_capability_case():
    r = recommend_next_action("price_request", 18, 45, "warm")
    assert r.next_action == ACTION_SEND_CAPABILITY_CASE


def test_not_interested_stop_sequence():
    r = recommend_next_action("not_interested", -30, 20, "cold")
    assert r.next_action == ACTION_STOP_SEQUENCE
    assert r.next_action_priority == "high"


def test_spam_suppress_contact():
    r = recommend_next_action("spam", -35, 10, "cold")
    assert r.next_action == ACTION_SUPPRESS_CONTACT
    assert r.next_action_priority == "high"


def test_no_response_warm_follow_up():
    # No dominant intent (no classified reply) but warm engagement.
    r = recommend_next_action(None, 0, 60, "warm")
    assert r.next_action == ACTION_FOLLOW_UP_SEQUENCE
    assert r.next_action_priority == "medium"


def test_no_response_cold_monitor():
    r = recommend_next_action(None, 0, 10, "cold")
    assert r.next_action == ACTION_MONITOR
    assert r.next_action_priority == "low"


def test_priority_from_label():
    assert priority_from_label("hot") == "high"
    assert priority_from_label("warm") == "medium"
    assert priority_from_label("cold") == "low"
    assert priority_from_label(None) == "low"
    assert priority_from_label("bogus") == "low"


def test_deterministic_pure():
    a = recommend_next_action("rfq_request", 90, 85, "hot")
    b = recommend_next_action("rfq_request", 90, 85, "hot")
    assert a.next_action == b.next_action
    assert a.next_action_priority == b.next_action_priority
    assert a.next_action_reason == b.next_action_reason


def test_reason_generation_present():
    r = recommend_next_action("rfq_request", 90, 85, "hot")
    assert r.next_action_reason
    assert "RFQ" in r.next_action_reason


# ---------------------------------------------------------------------------
# Service-level (DB-backed) behaviour
# ---------------------------------------------------------------------------
def _build_hot_rfq_lead(db):
    lead = _make_lead(db, "Hot RFQ Co")
    _add_reply(db, lead.id, "rfq_request", 100.0, text="send a formal quote")
    _add_reply(db, lead.id, "rfq_request", 95.0, text="also for the second part")
    _add_event(db, lead.id, "opened")
    _add_event(db, lead.id, "replied")
    _add_contact(db, lead.id, ranking_score=90)
    return lead


def test_rfq_hot_db_prepare_quote_high(db):
    lead = _build_hot_rfq_lead(db)
    sig = ConversionService(db).recompute_action(lead.id)
    assert sig.next_action == ACTION_PREPARE_QUOTE
    assert sig.next_action_priority == "high"
    assert sig.temperature_label == "hot"
    assert sig.next_action_reason


def test_technical_inquiry_db(db):
    lead = _make_lead(db, "Tech Co")
    _add_reply(db, lead.id, "technical_question", 80.0, text="can you do tight tolerances?")
    sig = ConversionService(db).recompute_action(lead.id)
    assert sig.next_action == ACTION_ENGINEERING_RESPONSE
    assert sig.next_action_reason


def test_interested_db(db):
    lead = _make_lead(db, "Interested Co")
    _add_reply(db, lead.id, "interested", 80.0, text="we are very interested")
    sig = ConversionService(db).recompute_action(lead.id)
    assert sig.next_action == ACTION_SEND_CAPABILITY_CASE
    assert sig.next_action_reason


def test_negative_db_stop_and_suppress(db):
    not_int = _make_lead(db, "NotInt")
    _add_reply(db, not_int.id, "not_interested", 80.0, text="not interested")
    s_not = ConversionService(db).recompute_action(not_int.id)
    assert s_not.next_action == ACTION_STOP_SEQUENCE
    assert s_not.next_action_priority == "high"

    spam = _make_lead(db, "Spam")
    _add_reply(db, spam.id, "spam", 90.0, text="buy cheap meds")
    s_spam = ConversionService(db).recompute_action(spam.id)
    assert s_spam.next_action == ACTION_SUPPRESS_CONTACT
    assert s_spam.next_action_priority == "high"


def test_no_response_warm_db_follow_up(db):
    lead = _make_lead(db, "Warm NoReply")
    for _ in range(5):
        _add_event(db, lead.id, "opened")
    sig = ConversionService(db).recompute_action(lead.id)
    assert sig.temperature_label in ("warm", "hot")
    assert sig.next_action == ACTION_FOLLOW_UP_SEQUENCE


def test_deterministic_db(db):
    lead = _build_hot_rfq_lead(db)
    svc = ConversionService(db)
    first = svc.recompute_action(lead.id)
    second = svc.recompute_action(lead.id)
    assert first.id == second.id
    assert first.next_action == second.next_action
    assert first.next_action_priority == second.next_action_priority
    assert first.next_action_reason == second.next_action_reason


def test_recompute_populates_all_three(db):
    lead = _build_hot_rfq_lead(db)
    sig = ConversionService(db).recompute(lead.id)
    # intent
    assert sig.intent_score is not None
    assert sig.dominant_intent == "rfq_request"
    # temperature
    assert sig.temperature_score is not None
    assert sig.temperature_label == "hot"
    # action
    assert sig.next_action == ACTION_PREPARE_QUOTE
    assert sig.next_action_priority == "high"
    assert sig.next_action_reason
