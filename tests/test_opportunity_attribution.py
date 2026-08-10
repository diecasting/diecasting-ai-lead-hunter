"""Phase 15.4.3: Opportunity attribution layer tests.

Verifies:
  1. An RFQ reply creates an Opportunity and attaches the existing
     ConversionSignal (conversion_signal_id set + temperature/intent copied).
  2. enhance_opportunity_probability() does NOT overwrite a manual probability.
  3. SET NULL cascade: deleting the ConversionSignal nulls conversion_signal_id.

Does NOT test Quote / SalesTask / email logic (out of scope).
"""
from app.conversion.service import ConversionService
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.opportunity import (
    PROBABILITY_SOURCE_CONVERSION,
    PROBABILITY_SOURCE_MANUAL,
    Opportunity,
    create_opportunity_from_rfq,
    enhance_opportunity_probability,
)
from app.outreach.reply_ai import analyzer as reply_analyzer


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _rfq_reply(db, lead):
    """Run a real rfq reply with CRM actions so an Opportunity is created."""
    analysis, _ = reply_analyzer.analyze_reply(
        db,
        lead,
        reply_text="Please quote 5000 pcs aluminum die cast housing, ADC12.",
        apply_actions=True,
    )
    return analysis


# ---------------------------------------------------------------------------
# 1. RFQ reply creates Opportunity with conversion_signal_id + copied scores
# ---------------------------------------------------------------------------
def test_rfq_reply_creates_opportunity_with_signal(db):
    lead = _make_lead(db, "AttrRfq")

    _rfq_reply(db, lead)

    opp = (
        db.query(Opportunity).filter(Opportunity.company_id == lead.id).first()
    )
    assert opp is not None

    # The signal the opportunity attached to (same lead, upserted by recompute).
    signal = ConversionService(db).get_signal(lead.id)
    assert signal is not None
    # Attribution bridge populated — the opp links to the same signal row.
    assert opp.conversion_signal_id == signal.id
    # Temperature / intent were copied from a signal snapshot at creation time
    # (the signal is recomputed again after the reply, so we assert the copy
    # happened with non-null values rather than exact live equality).
    assert opp.ai_temperature_score is not None
    assert opp.ai_intent_score is not None


# ---------------------------------------------------------------------------
# 2. AI probability does not overwrite manual probability
# ---------------------------------------------------------------------------
def test_ai_probability_does_not_overwrite_manual(db):
    lead = _make_lead(db, "ManualProb")

    # Build a signal with a known temperature + intent.
    signal = ConversionSignal(
        lead_id=lead.id,
        temperature_score=90,
        intent_score=80,
        dominant_intent="rfq_request",
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    opp = Opportunity(
        company_id=lead.id,
        stage="qualification",
        probability=99,  # manual call
        probability_source=PROBABILITY_SOURCE_MANUAL,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    # Enhance from the signal.
    enhanced = enhance_opportunity_probability(db, opp, signal=signal)
    # Manual probability preserved.
    assert enhanced.probability == 99
    assert enhanced.probability_source == PROBABILITY_SOURCE_MANUAL
    # AI suggestion is still recorded for reference.
    assert enhanced.ai_probability is not None
    assert 0 <= enhanced.ai_probability <= 100


def test_enhance_sets_conversion_source_when_not_manual(db):
    """When no manual source is set, enhance overwrites with conversion source."""
    lead = _make_lead(db, "AutoProb")

    signal = ConversionSignal(
        lead_id=lead.id,
        temperature_score=70,
        intent_score=20,
        dominant_intent="rfq_request",
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    opp = Opportunity(
        company_id=lead.id,
        stage="qualification",
        probability=10,  # stage baseline, not manual
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    enhanced = enhance_opportunity_probability(db, opp, signal=signal)
    assert enhanced.probability_source == PROBABILITY_SOURCE_CONVERSION
    assert enhanced.probability == enhanced.ai_probability
    assert enhanced.ai_probability is not None


# ---------------------------------------------------------------------------
# 3. SET NULL behavior
# ---------------------------------------------------------------------------
def test_conversion_signal_set_null_on_delete(db):
    lead = _make_lead(db, "SetNull")

    signal = ConversionSignal(
        lead_id=lead.id,
        temperature_score=60,
        intent_score=10,
        dominant_intent="rfq_request",
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    opp = Opportunity(
        company_id=lead.id,
        stage="qualification",
        conversion_signal_id=signal.id,
        ai_temperature_score=signal.temperature_score,
        ai_intent_score=signal.intent_score,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    assert opp.conversion_signal_id == signal.id

    # Delete the signal; FK ondelete=SET NULL should null the link.
    db.delete(signal)
    db.commit()
    db.refresh(opp)
    assert opp.conversion_signal_id is None
    # Copied scores remain (they are independent columns).
    assert opp.ai_temperature_score == 60
