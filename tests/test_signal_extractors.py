"""Tests for Phase 16.2 internal signal extraction engine.

Covers the multilingual RFQ scanner, all four source adapters, idempotent
dedup via Phase 16.1 ingestion, and the :class:`SignalExtractionService`
bridges. Asserts the hard constraints: no ``lead_score`` mutation, no schema
change, fully deterministic.
"""
import pytest

from app.conversion.intent import BASE_POINTS
from app.intent.extractors import (
    SignalExtractionService,
    build_conversion_signals,
    build_legacy_buying_signal,
    build_reply_intent_signals,
    build_rfq_keyword_signals,
    build_website_signals,
)
from app.intent.keywords import RFQ_KEYWORDS, SUPPORTED_LANGUAGES, scan_keywords
from app.intent.service import SignalEventService
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis
from app.models.signal_event import SIGNAL_VALUE_MAX, SIGNAL_VALUE_MIN, SignalEvent


# ---------------------------------------------------------------------------
# Multilingual scanner
# ---------------------------------------------------------------------------
def test_scan_keywords_unsupported_lang_falls_back_to_en():
    # Unknown code must not crash and falls back to EN.
    out = scan_keywords("looking for suppliers", lang="FR")
    assert out["level"] == "HIGH"


def test_scan_keywords_en_high():
    out = scan_keywords("Please send us your rfq for aluminum die casting", lang="EN")
    assert out["level"] == "HIGH"
    assert "rfq" in out["matched"]


def test_scan_keywords_en_medium():
    out = scan_keywords("We are a manufacturer of precision components", lang="EN")
    assert out["level"] == "MEDIUM"


def test_scan_keywords_en_low():
    out = scan_keywords("We are a distributor and trader of metals", lang="EN")
    assert out["level"] == "LOW"


def test_scan_keywords_en_none():
    out = scan_keywords("Welcome to our corporate website", lang="EN")
    assert out["level"] == "NONE"
    assert out["matched"] == []


def test_scan_keywords_de_high():
    out = scan_keywords(
        "Wir suchen einen Lieferanten fuer Aluminiumdruckguss. Angebotsanfrage.",
        lang="DE",
    )
    assert out["level"] == "HIGH"
    assert "angebotsanfrage" in out["matched"]
    assert "aluminiumdruckguss" in out["matched"]


def test_scan_keywords_auto_merges_languages():
    text = "request for quotation Lieferanten gesucht"
    out = scan_keywords(text, lang="AUTO")
    assert out["level"] == "HIGH"
    assert "request for quotation" in out["matched"]
    assert "lieferanten gesucht" in out["matched"]


def test_scan_keywords_dedup_substring():
    # "anfrage" must not be double-counted inside "angebotsanfrage".
    out = scan_keywords("angebotsanfrage", lang="DE")
    assert out["level"] == "HIGH"
    assert "angebotsanfrage" in out["matched"]
    assert "anfrage" not in out["matched"]


def test_scan_keywords_deterministic():
    text = "looking for suppliers sourcing rfq"
    assert scan_keywords(text, "EN") == scan_keywords(text, "EN")


# ---------------------------------------------------------------------------
# Adapter 1: website extractor (reuses existing analyzer)
# ---------------------------------------------------------------------------
def test_build_website_signals_high():
    sigs = build_website_signals(1, "We are looking for suppliers and request for quotation")
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "website_change"
    assert s.signal_type == "website_buying_signal"
    assert s.value == 70
    assert s.intent_category == "purchase"
    assert s.external_id == "website:1"


def test_build_website_signals_none_empty():
    assert build_website_signals(1, "nothing relevant here") == []


# ---------------------------------------------------------------------------
# Adapter 2: RFQ keyword extractor (multilingual)
# ---------------------------------------------------------------------------
def test_build_rfq_keyword_signals_de():
    sigs = build_rfq_keyword_signals(2, "Aluminiumdruckguss Angebotsanfrage", lang="DE")
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "rfq_keyword"
    assert s.value == 75
    assert s.metadata["lang"] == "DE"


def test_build_rfq_keyword_signals_none():
    assert build_rfq_keyword_signals(2, "welcome to our corporate website about general topics", lang="EN") == []


# ---------------------------------------------------------------------------
# Adapter 3a: reply intent bridge
# ---------------------------------------------------------------------------
def test_build_reply_intent_signals_positive():
    a = ReplyAnalysis(
        lead_id=10, reply_text="Please send a quote", intent="rfq_request", confidence_score=90.0
    )
    sigs = build_reply_intent_signals(a)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "reply_intent"
    assert s.signal_type == "reply:rfq_request"
    assert s.value == BASE_POINTS["rfq_request"]  # 45
    assert s.confidence == 90
    assert s.intent_category == "purchase"
    assert s.external_id == "reply:None"  # id not yet assigned


def test_build_reply_intent_signals_negative():
    a = ReplyAnalysis(lead_id=10, reply_text="not interested", intent="not_interested")
    s = build_reply_intent_signals(a)[0]
    assert s.value == BASE_POINTS["not_interested"]  # -30
    assert s.intent_category == "deterrent"


def test_build_reply_intent_signals_neutral():
    a = ReplyAnalysis(lead_id=10, reply_text="out of office", intent="out_of_office")
    s = build_reply_intent_signals(a)[0]
    assert s.value == 0
    assert s.intent_category == "research"


# ---------------------------------------------------------------------------
# Adapter 3b: conversion bridge
# ---------------------------------------------------------------------------
def test_build_conversion_signals_positive():
    cs = ConversionSignal(lead_id=10, intent_score=45, dominant_intent="rfq_request")
    s = build_conversion_signals(cs)[0]
    assert s.source == "reply_intent"
    assert s.signal_type == "conversion_snapshot"
    assert s.value == 45
    assert s.confidence == 45
    assert s.intent_category == "purchase"


def test_build_conversion_signals_negative():
    cs = ConversionSignal(lead_id=10, intent_score=-35, dominant_intent="spam")
    s = build_conversion_signals(cs)[0]
    assert s.value == -35
    assert s.intent_category == "deterrent"


def test_build_conversion_signals_none_score_empty():
    cs = ConversionSignal(lead_id=10, intent_score=None)
    assert build_conversion_signals(cs) == []


# ---------------------------------------------------------------------------
# Adapter 4: legacy migration helper
# ---------------------------------------------------------------------------
def test_build_legacy_buying_signal_with_detail():
    sigs = build_legacy_buying_signal(3, "HIGH (rfq; sourcing)")
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "manual"
    assert s.signal_type == "legacy_buying_signal"
    assert s.value == 70
    assert s.external_id == "legacy:3"


def test_build_legacy_buying_signal_level_only():
    s = build_legacy_buying_signal(3, "MEDIUM")[0]
    assert s.value == 35
    assert s.intent_category == "purchase"


def test_build_legacy_buying_signal_invalid_level():
    assert build_legacy_buying_signal(3, "UNKNOWN (x)") == []
    assert build_legacy_buying_signal(3, None) == []
    assert build_legacy_buying_signal(3, "") == []


# ---------------------------------------------------------------------------
# Idempotent ingestion (Phase 16.1 dedup_key)
# ---------------------------------------------------------------------------
def test_ingest_website_idempotent(db):
    svc = SignalExtractionService(db)
    first = svc.extract_website(100, "looking for suppliers request for quotation")
    second = svc.extract_website(100, "looking for suppliers request for quotation")
    assert first is not None and second is not None
    assert first.created is True
    assert second.created is False
    assert second.updated is True
    # Exactly one row for this company (dedup by external_id).
    rows = db.query(SignalEvent).filter(SignalEvent.company_id == 100).all()
    assert len(rows) == 1


def test_ingest_rfq_and_website_distinct(db):
    svc = SignalExtractionService(db)
    svc.extract_website(101, "looking for suppliers")
    svc.extract_rfq_keywords(101, "looking for suppliers", lang="EN")
    rows = (
        db.query(SignalEvent)
        .filter(SignalEvent.company_id == 101)
        .all()
    )
    # Different source/signal_type -> two distinct rows, not deduped together.
    assert len(rows) == 2
    sources = {r.source for r in rows}
    assert "website_change" in sources and "rfq_keyword" in sources


# ---------------------------------------------------------------------------
# Service bridges + constraint checks
# ---------------------------------------------------------------------------
def test_bridge_replies_for_lead(db):
    lead = CompanyLead(name="Lead A")
    db.add(lead)
    db.flush()
    db.add_all(
        [
            ReplyAnalysis(
                lead_id=lead.id, reply_text="send quote", intent="rfq_request", confidence_score=80.0
            ),
            ReplyAnalysis(
                lead_id=lead.id, reply_text="not now", intent="not_interested", confidence_score=70.0
            ),
        ]
    )
    db.commit()

    svc = SignalExtractionService(db)
    results = svc.bridge_replies_for_lead(lead.id)
    assert len(results) == 2
    values = {r.signal.value for r in results}
    assert BASE_POINTS["rfq_request"] in values
    assert BASE_POINTS["not_interested"] in values

    stored = (
        db.query(SignalEvent)
        .filter(SignalEvent.company_id == lead.id, SignalEvent.source == "reply_intent")
        .all()
    )
    assert len(stored) == 2


def test_bridge_conversions_for_lead(db):
    lead = CompanyLead(name="Lead B")
    db.add(lead)
    db.flush()
    db.add(ConversionSignal(lead_id=lead.id, intent_score=60, dominant_intent="rfq_request"))
    db.commit()

    svc = SignalExtractionService(db)
    results = svc.bridge_conversions_for_lead(lead.id)
    assert len(results) == 1
    assert results[0].signal.value == 60
    assert results[0].signal.signal_type == "conversion_snapshot"


def test_migrate_company_does_not_change_lead_score(db):
    lead = CompanyLead(
        name="Lead C",
        website_content="We are looking for suppliers of aluminum die casting. request for quotation.",
        buying_signal="HIGH (rfq; sourcing)",
        lead_score=88,
    )
    db.add(lead)
    db.commit()

    svc = SignalExtractionService(db)
    results = svc.migrate_company(lead, lang="AUTO")
    # website (HIGH) + rfq AUTO (HIGH) + legacy (HIGH) = 3 signals.
    assert len(results) == 3

    db.refresh(lead)
    # Hard constraint: lead_score untouched by the extraction engine.
    assert lead.lead_score == 88

    stored = db.query(SignalEvent).filter(SignalEvent.company_id == lead.id).all()
    assert len(stored) == 3
    assert all(SIGNAL_VALUE_MIN <= s.value <= SIGNAL_VALUE_MAX for s in stored)


def test_package_exports():
    import app.intent as pkg

    assert hasattr(pkg, "SignalExtractionService")
    assert hasattr(pkg, "scan_keywords")
    assert "EN" in SUPPORTED_LANGUAGES and "DE" in SUPPORTED_LANGUAGES
    assert "EN" in RFQ_KEYWORDS and "DE" in RFQ_KEYWORDS
