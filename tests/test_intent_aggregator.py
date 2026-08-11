"""Phase 16.3: Intent Aggregation Layer — unit + integration tests.

Covers (per the Phase 16.3 spec):
  * strong recent signal        -> high buying_intent_score + HOT/WARM temp
  * stale signal decay          -> low timing_score, cooled temperature
  * multiple signal aggregation -> corroboration raises score + source count
  * temperature classification  -> HOT/WARM/COOL/COLD/NONE buckets
  * empty signal case           -> all-zero / NONE snapshot
  * hard constraint             -> lead_score / sales_priority never modified
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.intent.aggregator import (
    IntentAggregator,
    IntentSnapshot,
    aggregate_signals,
    classify_temperature,
)
from app.intent.service import SignalEventService, SignalInput
from app.models.signal_event import (
    SOURCE_RFQ_KEYWORD,
    SOURCE_REPLY_INTENT,
    SOURCE_WEBSITE_CHANGE,
    SignalEvent,
)


def _signal(value, confidence, detected_at, source=SOURCE_RFQ_KEYWORD, signal_type="rfq"):
    return SignalEvent(
        id=None,
        company_id=1,
        source=source,
        signal_type=signal_type,
        intent_category="purchase",
        value=value,
        confidence=confidence,
        detected_at=detected_at,
        is_active=True,
        dedup_key=f"{source}|{signal_type}|{detected_at.isoformat()}",
    )


# --- pure-function tests (no DB) ------------------------------------------------

def test_empty_signal_case():
    snap = aggregate_signals([])
    assert snap.buying_intent_score == 0
    assert snap.timing_score == 0
    assert snap.intent_temperature == "NONE"
    assert snap.last_signal_at is None
    assert snap.intent_source_count == 0
    assert snap.intent_sources == []


def test_strong_recent_signal():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    recent = now - timedelta(days=1)
    snap = aggregate_signals(
        [_signal(90, 95, recent, SOURCE_RFQ_KEYWORD, "rfq")], now=now
    )
    assert snap.buying_intent_score >= 70
    assert snap.timing_score >= 90
    assert snap.intent_temperature in ("HOT", "WARM")
    assert snap.intent_source_count == 1
    assert snap.last_signal_at == recent


def test_stale_signal_decay():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    stale = now - timedelta(days=40)  # beyond TIMING_FULL_DECAY_DAYS
    snap = aggregate_signals(
        [_signal(90, 95, stale, SOURCE_RFQ_KEYWORD, "rfq")], now=now
    )
    assert snap.timing_score == 0
    # strong but ancient -> cooled to COLD (effective intent ~ 0)
    assert snap.intent_temperature == "COLD"
    assert snap.buying_intent_score >= 0


def test_multiple_signal_aggregation():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    recent = now - timedelta(days=2)
    single = aggregate_signals(
        [_signal(80, 90, recent, SOURCE_RFQ_KEYWORD, "rfq")], now=now
    )
    multi = aggregate_signals(
        [
            _signal(80, 90, recent, SOURCE_RFQ_KEYWORD, "rfq"),
            _signal(70, 85, recent, SOURCE_REPLY_INTENT, "reply"),
            _signal(60, 80, recent, SOURCE_WEBSITE_CHANGE, "website"),
        ],
        now=now,
    )
    # More distinct sources -> stronger corroboration factor -> higher score.
    assert multi.buying_intent_score > single.buying_intent_score
    assert multi.intent_source_count == 3
    assert multi.intent_sources == sorted(
        [SOURCE_RFQ_KEYWORD, SOURCE_REPLY_INTENT, SOURCE_WEBSITE_CHANGE]
    )


def test_temperature_classification_boundaries():
    # Pure classifier checks (buying_intent_score, timing_score) -> label.
    # Bands are strict & non-overlapping: <=0 NONE; <30 COLD; <50 COOL;
    # <70 WARM; >=70 HOT. A score exactly on a boundary takes the higher band.
    assert classify_temperature(0, 0) == "NONE"
    assert classify_temperature(20, 100) == "COLD"      # effective 20
    assert classify_temperature(30, 100) == "COOL"      # effective 30
    assert classify_temperature(50, 100) == "WARM"      # effective 50
    assert classify_temperature(80, 100) == "HOT"       # effective 80
    assert classify_temperature(95, 100) == "HOT"       # effective 95
    # Old signal cools a strong score.
    assert classify_temperature(95, 10) == "COLD"       # effective 9.5


def test_deterrent_signal_lowers_score():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    recent = now - timedelta(days=1)
    snap = aggregate_signals(
        [_signal(-60, 90, recent, SOURCE_REPLY_INTENT, "reply")], now=now
    )
    # negative value -> normalized strength below 50 -> final score below 50
    assert snap.buying_intent_score < 50


# --- DB-backed integration tests (conftest `db` fixture) -----------------------

def test_aggregate_for_company_integration(db):
    from app.models.lead import CompanyLead

    lead = CompanyLead(name="AggregateCo", website="https://agg.example.com")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    recent = now - timedelta(days=1)
    svc = SignalEventService(db)
    svc.ingest(
        SignalInput(
            source=SOURCE_RFQ_KEYWORD,
            signal_type="rfq",
            value=85,
            company_id=lead.id,
            confidence=95,
            detected_at=recent,
            external_id="evt-1",
        )
    )
    db.commit()

    agg = IntentAggregator(db)
    snap = agg.aggregate_for_company(lead.id, now=now)
    assert snap.buying_intent_score >= 70
    assert snap.intent_source_count == 1
    assert snap.intent_temperature in ("HOT", "WARM")


def test_recompute_does_not_change_lead_score(db):
    """Hard constraint: recompute must not touch lead_score / sales_priority."""
    from app.models.lead import CompanyLead

    lead = CompanyLead(
        name="NoTouchCo",
        website="https://notouch.example.com",
        lead_score=88,
        sales_priority="HIGH",
        priority="HIGH",
        buying_signal="HIGH (rfq)",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    svc = SignalEventService(db)
    svc.ingest(
        SignalInput(
            source=SOURCE_RFQ_KEYWORD,
            signal_type="rfq",
            value=80,
            company_id=lead.id,
            confidence=90,
            detected_at=now - timedelta(days=1),
            external_id="evt-nt",
        )
    )
    db.commit()

    # Import the recompute logic directly (no DB session side effects on score).
    from scripts.recompute_intent import recompute

    updated, skipped = recompute(db, company_ids=[lead.id])
    db.commit()
    db.refresh(lead)

    assert updated == 1
    # Snapshot columns populated:
    assert lead.buying_intent_score is not None
    assert lead.intent_temperature in ("HOT", "WARM", "COOL", "COLD")
    # Protected columns untouched:
    assert lead.lead_score == 88
    assert lead.sales_priority == "HIGH"
    assert lead.priority == "HIGH"
    assert lead.buying_signal == "HIGH (rfq)"
