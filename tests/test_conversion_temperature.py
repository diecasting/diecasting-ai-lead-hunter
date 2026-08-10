"""Phase 15.1.3: Lead Temperature Engine.

Deterministic, offline tests — no LLM, no network. Exercises the temperature
math directly and through :class:`app.conversion.service.ConversionService`
against the in-memory SQLite fixture.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.conversion import (
    ConversionService,
    combine_temperature,
    contact_component,
    engagement_component,
    intent_strength_component,
    label_for_score,
    recency_component,
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


def _set_activity(db, lead, age_days):
    lead.last_activity_time = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.commit()


# ---------------------------------------------------------------------------
# Pure component math
# ---------------------------------------------------------------------------
def test_intent_strength_transform():
    # signed intent (-100..100) -> 0..100
    assert intent_strength_component(-100) == 0.0
    assert intent_strength_component(0) == 50.0
    assert intent_strength_component(100) == 100.0
    assert intent_strength_component(None) == 0.0


def test_recency_component_fresh_and_decay():
    assert recency_component(0) == 100.0
    # one half-life -> ~50
    assert recency_component(30) == pytest.approx(50.0, abs=0.5)
    # very old -> near 0
    assert recency_component(180) < 5.0


def test_engagement_component():
    assert engagement_component(0) == 0.0
    assert engagement_component(3) == 30.0  # 3 units * 10
    assert engagement_component(20) == 100.0  # clamped


def test_contact_component():
    assert contact_component(None) == 0.0
    assert contact_component(80) == 80.0
    assert contact_component(150) == 100.0  # clamped


def test_combine_temperature_weights_and_bounds():
    # All-max -> 100
    assert combine_temperature(100, 100, 100, 100) == 100
    # All-zero -> 0 (cold)
    assert combine_temperature(0, 0, 0, 0) == 0
    # Weighted sum: 80*0.4 + 50*0.25 + 30*0.2 + 10*0.15 = 32 + 12.5 + 6 + 1.5 = 52
    assert combine_temperature(80, 50, 30, 10) == 52


def test_label_boundaries():
    assert label_for_score(0) == "cold"
    assert label_for_score(30) == "cold"
    assert label_for_score(31) == "warm"
    assert label_for_score(70) == "warm"
    assert label_for_score(71) == "hot"
    assert label_for_score(100) == "hot"


# ---------------------------------------------------------------------------
# Service-level (DB-backed) behaviour
# ---------------------------------------------------------------------------
def test_recent_rfq_reply_produces_hot(db):
    lead = _make_lead(db, "Hot RFQ Co")
    _add_reply(db, lead.id, "rfq_request", 100.0, text="send a formal quote")
    _add_reply(db, lead.id, "rfq_request", 95.0, text="also for the second part")
    _add_event(db, lead.id, "opened")
    _add_event(db, lead.id, "replied")
    _add_contact(db, lead.id, ranking_score=90)
    sig = ConversionService(db).recompute_temperature(lead.id)
    assert sig.temperature_score > 70
    assert sig.temperature_label == "hot"
    assert sig.temperature_reason


def test_old_rfq_decays_to_cold(db):
    recent = _make_lead(db, "Recent RFQ")
    _add_reply(db, recent.id, "rfq_request", 95.0, age_days=0)

    old = _make_lead(db, "Old RFQ")
    _add_reply(db, old.id, "rfq_request", 95.0, age_days=120)

    svc = ConversionService(db)
    s_recent = svc.recompute_temperature(recent.id)
    s_old = svc.recompute_temperature(old.id)

    # The recent RFQ is clearly hotter than the stale one.
    assert s_recent.temperature_score > s_old.temperature_score
    # A 120-day-old single RFQ should not be hot (recency collapse + decayed intent).
    assert s_old.temperature_score < 71
    assert s_recent.temperature_label in ("warm", "hot")
    assert s_old.temperature_label == "cold"


def test_bounce_lowers_temperature(db):
    base = _make_lead(db, "Opened Base")
    _add_event(db, base.id, "opened")
    _add_event(db, base.id, "opened")
    _add_event(db, base.id, "opened")
    _add_event(db, base.id, "opened")
    _add_event(db, base.id, "opened")

    bounced = _make_lead(db, "Opened + Bounce")
    _add_event(db, bounced.id, "opened")
    _add_event(db, bounced.id, "opened")
    _add_event(db, bounced.id, "opened")
    _add_event(db, bounced.id, "opened")
    _add_event(db, bounced.id, "opened")
    _add_event(db, bounced.id, "bounced")

    svc = ConversionService(db)
    s_base = svc.recompute_temperature(base.id)
    s_bounced = svc.recompute_temperature(bounced.id)

    assert s_bounced.temperature_score < s_base.temperature_score


def test_high_ranking_contact_increases_temperature(db):
    no_contact = _make_lead(db, "No Contact")
    _add_reply(db, no_contact.id, "rfq_request", 95.0, age_days=0)
    _set_activity(db, no_contact, 0)

    ranked = _make_lead(db, "Ranked Contact")
    _add_reply(db, ranked.id, "rfq_request", 95.0, age_days=0)
    _set_activity(db, ranked, 0)
    _add_contact(db, ranked.id, ranking_score=90)

    svc = ConversionService(db)
    s_no = svc.recompute_temperature(no_contact.id)
    s_ranked = svc.recompute_temperature(ranked.id)

    assert s_ranked.temperature_score > s_no.temperature_score
    # Only the contact axis differs (15% weight of 90 ~= 13.5).
    assert (s_ranked.temperature_score - s_no.temperature_score) >= 10


def test_do_not_contact_excluded_from_ranking(db):
    lead = _make_lead(db, "Blocked Contact")
    _add_reply(db, lead.id, "rfq_request", 95.0, age_days=0)
    _add_contact(db, lead.id, ranking_score=99, do_not_contact=True)
    sig = ConversionService(db).recompute_temperature(lead.id)
    # Blocked contact must NOT boost the temperature via the contact axis.
    assert sig.temperature_reason is not None
    # (contact component contributes 0 because the only ranked contact is blocked)
    assert "contact_ranking=None" in sig.temperature_reason


def test_deterministic_output(db):
    lead = _make_lead(db, "Det Temp Co")
    _add_reply(db, lead.id, "rfq_request", 88.0)
    _add_reply(db, lead.id, "interested", 70.0)
    _add_event(db, lead.id, "opened")
    _add_contact(db, lead.id, ranking_score=75)
    svc = ConversionService(db)
    first = svc.recompute_temperature(lead.id)
    second = svc.recompute_temperature(lead.id)
    assert first.id == second.id
    assert first.temperature_score == second.temperature_score
    assert first.temperature_label == second.temperature_label
    assert first.temperature_reason == second.temperature_reason


def test_recompute_populates_intent_and_temperature(db):
    lead = _make_lead(db, "Combo Co")
    _add_reply(db, lead.id, "rfq_request", 95.0)
    sig = ConversionService(db).recompute(lead.id)
    assert sig.intent_score is not None
    assert sig.temperature_score is not None
    assert sig.temperature_label in ("cold", "warm", "hot")
    assert sig.temperature_reason


def test_temperature_reason_includes_breakdown(db):
    lead = _make_lead(db, "Reason Co")
    _add_reply(db, lead.id, "rfq_request", 95.0)
    sig = ConversionService(db).recompute_temperature(lead.id)
    reason = sig.temperature_reason
    assert "intent_score=" in reason
    assert "recency" in reason
    assert "engagement" in reason
    assert "contact_ranking" in reason
    assert "=> temperature" in reason
