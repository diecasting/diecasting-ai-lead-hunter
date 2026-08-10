"""Phase 15.2.1: Conversion Intelligence Wiring tests.

Verifies that :func:`app.outreach.reply_ai.analyzer.analyze_reply` automatically
recomputes the lead's conversion snapshot (intent / temperature / next action)
via :class:`app.conversion.service.ConversionService` after a ReplyAnalysis is
created, and that recompute failures are isolated (never break reply analysis).

All tests are offline: no LLM, no network. ``apply_actions=False`` keeps the
tests focused on the conversion wiring (the CRM automation path is covered by
the Phase 10 suite) while the analyzer's timeline milestone still fires.
"""
import pytest

from app.conversion.service import ConversionService
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.outreach_event import OutreachEvent
from app.models.reply_analysis import ReplyAnalysis
from app.outreach.reply_ai import analyzer as reply_analyzer


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _signal(db, lead_id):
    return (
        db.query(ConversionSignal)
        .filter(ConversionSignal.lead_id == lead_id)
        .first()
    )


# ---------------------------------------------------------------------------
# RFQ reply -> conversion snapshot updated (intent + prepare_quote action)
# ---------------------------------------------------------------------------
def test_rfq_reply_updates_conversion_signal(db):

    lead = _make_lead(db, "WireRfq")

    analysis, _actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please send us a quote for 5000 pcs ADC12 die casting housing, ASAP.",
        apply_actions=False,
    )
    assert analysis.intent == "rfq_request"

    sig = _signal(db, lead.id)
    assert sig is not None, "ConversionSignal must be created/updated by wiring"
    assert sig.intent_score is not None and sig.intent_score > 0
    assert sig.dominant_intent == "rfq_request"
    assert sig.temperature_score is not None and sig.temperature_score >= 0
    assert sig.next_action == "prepare_quote"
    assert sig.next_action_priority == "high"
    assert sig.next_action_reason
    assert sig.temperature_reason


# ---------------------------------------------------------------------------
# Interested reply -> capability-case action
# ---------------------------------------------------------------------------
def test_interested_reply_updates_action(db):

    lead = _make_lead(db, "WireInterested")

    analysis, _actions = reply_analyzer.analyze_reply(
        db, lead, reply_text="We are very interested, please send more info.", apply_actions=False
    )
    assert analysis.intent == "interested"

    sig = _signal(db, lead.id)
    assert sig is not None
    assert sig.dominant_intent == "interested"
    assert sig.next_action == "send_capability_case"
    assert sig.next_action_priority in ("medium", "high")


# ---------------------------------------------------------------------------
# Negative replies -> stop / suppress action
# ---------------------------------------------------------------------------
def test_not_interested_reply_updates_stop_action(db):

    lead = _make_lead(db, "WireNotInterested")

    analysis, _actions = reply_analyzer.analyze_reply(
        db, lead, reply_text="Not interested, please remove us from your list.", apply_actions=False
    )
    assert analysis.intent == "not_interested"

    sig = _signal(db, lead.id)
    assert sig is not None
    assert sig.dominant_intent == "not_interested"
    assert sig.next_action == "stop_sequence"
    assert sig.next_action_priority == "high"


def test_spam_reply_updates_suppress_action(db):

    lead = _make_lead(db, "WireSpam")

    analysis, _actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Congratulations you won a prize, claim your free gift now!",
        apply_actions=False,
    )
    assert analysis.intent == "spam"

    sig = _signal(db, lead.id)
    assert sig is not None
    assert sig.dominant_intent == "spam"
    assert sig.next_action == "suppress_contact"
    assert sig.next_action_priority == "high"


# ---------------------------------------------------------------------------
# Recompute failure is isolated: reply analysis still completes
# ---------------------------------------------------------------------------
def test_recompute_failure_does_not_break_reply_analysis(db, monkeypatch):

    lead = _make_lead(db, "WireFail")

    def _boom(self, lead_id):  # raises before any DB work inside recompute
        raise RuntimeError("injected recompute failure")

    monkeypatch.setattr(ConversionService, "recompute", _boom)

    # Must not raise; reply analysis + timeline must still complete.
    analysis, actions = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please send us a quote for 1000 pcs zinc die casting.",
        apply_actions=False,
    )
    assert analysis.intent == "rfq_request"

    # ReplyAnalysis was persisted.
    persisted = (
        db.query(ReplyAnalysis)
        .filter(ReplyAnalysis.lead_id == lead.id)
        .first()
    )
    assert persisted is not None
    assert persisted.intent == "rfq_request"

    # Timeline 'replied' milestone still recorded (rfq_request is a real reply).
    replied = (
        db.query(OutreachEvent)
        .filter(OutreachEvent.lead_id == lead.id, OutreachEvent.event_type == "replied")
        .first()
    )
    assert replied is not None

    # ConversionSignal was NOT created because recompute failed entirely.
    assert _signal(db, lead.id) is None
