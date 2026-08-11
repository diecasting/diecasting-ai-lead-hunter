"""Intent Event Foundation + Internal Signal Extraction Engine + Aggregation.

Storage + deterministic ingestion layer for :class:`SignalEvent` (Phase 16.1),
the source-adapter layer converting existing internal data into signal events
(Phase 16.2), and the deterministic aggregation layer turning those events into
a per-lead intent snapshot (Phase 16.3).

  * :mod:`app.intent.repository` — thin, side-effect-free DB access.
  * :mod:`app.intent.service`    — deterministic dedup / upsert orchestration.
  * :mod:`app.intent.keywords`   — multilingual (EN/DE) RFQ keyword dictionary.
  * :mod:`app.intent.extractors` — 4 source adapters + :class:`SignalExtractionService`.
  * :mod:`app.intent.aggregator` — :class:`IntentAggregator` + :class:`IntentSnapshot`.

This package contains NO external API calls, NO LLM, NO scoring logic and NO
changes to lead / opportunity / contact scoring. The aggregator only *reads*
signal_events and writes the six isolated snapshot columns on CompanyLead.
"""

from app.intent.aggregator import (
    IntentAggregator,
    IntentSnapshot,
    aggregate_signals,
    classify_temperature,
)
from app.intent.extractors import (
    SignalExtractionService,
    build_conversion_signals,
    build_legacy_buying_signal,
    build_reply_intent_signals,
    build_rfq_keyword_signals,
    build_website_signals,
)
from app.intent.keywords import RFQ_KEYWORDS, SUPPORTED_LANGUAGES, scan_keywords
from app.intent.service import IngestResult, SignalEventService, SignalInput

__all__ = [
    "SignalEventService",
    "SignalInput",
    "IngestResult",
    "RFQ_KEYWORDS",
    "SUPPORTED_LANGUAGES",
    "scan_keywords",
    "SignalExtractionService",
    "build_website_signals",
    "build_rfq_keyword_signals",
    "build_reply_intent_signals",
    "build_conversion_signals",
    "build_legacy_buying_signal",
    "IntentAggregator",
    "IntentSnapshot",
    "aggregate_signals",
    "classify_temperature",
]
