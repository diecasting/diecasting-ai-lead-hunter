"""Phase 15.1.1 / 15.1.2: Conversion Signal Foundation + Intent Score Engine.

Deterministic, offline tests — no LLM, no network. Exercises the scoring math
directly and through :class:`app.conversion.service.ConversionService` against
the in-memory SQLite fixture.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.conversion import ConversionService, score_reply, score_event
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


# ---------------------------------------------------------------------------
# Pure scoring math
# ---------------------------------------------------------------------------
def test_rfq_high_positive():
    # base 45 * full confidence -> ~45
    assert score_reply("rfq_request", 100.0, 0) == 45.0


def test_interested_positive_medium():
    # base 30 * 0.8 -> 24
    assert score_reply("interested", 80.0, 0) == 24.0


def test_negative_intent_negative():
    assert score_reply("not_interested", 100.0, 0) == -30.0
    assert score_reply("spam", 100.0, 0) == -35.0


def test_confidence_weighting():
    low = score_reply("rfq_request", 40.0, 0)
    high = score_reply("rfq_request", 95.0, 0)
    assert low == 18.0
    assert high == 42.75
    assert high > low


def test_recency_decay():
    fresh = score_reply("rfq_request", 100.0, 0)
    old = score_reply("rfq_request", 100.0, 30)  # one half-life -> half
    assert old == pytest.approx(fresh / 2)
    assert fresh > old


def test_event_scoring():
    assert score_event("opened", 0) == 5
    assert score_event("bounced", 0) == -10
    assert score_event("sent", 0) == 0  # ignored (outbound)
    assert score_event("replied", 0) == 0  # covered by ReplyAnalysis


# ---------------------------------------------------------------------------
# Service-level (DB-backed) behaviour
# ---------------------------------------------------------------------------
def test_rfq_reply_gets_high_intent_score(db):
    lead = _make_lead(db, "RFQ Co")
    _add_reply(db, lead.id, "rfq_request", 90.0, text="please send a quote")
    sig = ConversionService(db).recompute_intent_score(lead.id)
    assert sig.intent_score > 30  # high
    assert sig.dominant_intent == "rfq_request"


def test_interested_reply_gets_medium_score(db):
    lead = _make_lead(db, "Interested Co")
    _add_reply(db, lead.id, "interested", 80.0, text="we are very interested")
    sig = ConversionService(db).recompute_intent_score(lead.id)
    # medium: clearly less than a fresh high-confidence RFQ, clearly positive
    assert 15 <= sig.intent_score <= 35
    assert sig.intent_score < 40
    assert sig.dominant_intent == "interested"


def test_negative_reply_lowers_score(db):
    only_interested = _make_lead(db, "A")
    _add_reply(db, only_interested.id, "interested", 80.0)
    s_a = ConversionService(db).recompute_intent_score(only_interested.id)

    mixed = _make_lead(db, "B")
    _add_reply(db, mixed.id, "interested", 80.0)
    _add_reply(db, mixed.id, "not_interested", 80.0, text="not interested")
    s_b = ConversionService(db).recompute_intent_score(mixed.id)

    assert s_a.intent_score > s_b.intent_score  # negative reply lowers it
    # a pure negative reply is itself negative
    neg = _make_lead(db, "C")
    _add_reply(db, neg.id, "not_interested", 80.0)
    s_c = ConversionService(db).recompute_intent_score(neg.id)
    assert s_c.intent_score < 0


def test_opened_event_adds_weak_positive_no_dominant(db):
    lead = _make_lead(db, "Opened Co")
    _add_event(db, lead.id, "opened")
    sig = ConversionService(db).recompute_intent_score(lead.id)
    assert sig.intent_score > 0  # weak positive from engagement
    assert sig.dominant_intent is None  # no classified reply drove it


def test_deterministic_output(db):
    lead = _make_lead(db, "Det Co")
    _add_reply(db, lead.id, "rfq_request", 88.0)
    _add_reply(db, lead.id, "interested", 70.0)
    svc = ConversionService(db)
    first = svc.recompute_intent_score(lead.id)
    second = svc.recompute_intent_score(lead.id)
    # Same row (upsert) and identical score -> deterministic.
    assert first.id == second.id
    assert first.intent_score == second.intent_score
    assert first.dominant_intent == second.dominant_intent


def test_score_clamped_at_ceiling(db):
    lead = _make_lead(db, "Hot Co")
    for _ in range(5):  # 5 * (45 * 1.0) = 225 -> clamp 100
        _add_reply(db, lead.id, "rfq_request", 100.0)
    sig = ConversionService(db).recompute_intent_score(lead.id)
    assert sig.intent_score == 100


def test_signal_sources_persisted(db):
    lead = _make_lead(db, "Src Co")
    _add_reply(db, lead.id, "rfq_request", 90.0)
    sig = ConversionService(db).recompute_intent_score(lead.id)
    assert sig.signal_sources is not None
    import json

    sources = json.loads(sig.signal_sources)
    assert sources["method"].startswith("deterministic")
    assert len(sources["reply_analyses"]) == 1
    assert sources["reply_analyses"][0]["intent"] == "rfq_request"
