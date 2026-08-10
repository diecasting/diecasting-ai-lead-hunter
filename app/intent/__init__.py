"""Intent Event Foundation + Internal Signal Extraction Engine.

Storage + deterministic ingestion layer for :class:`SignalEvent` (Phase 16.1),
plus the source-adapter layer that converts existing internal data into
signal events (Phase 16.2).

  * :mod:`app.intent.repository` — thin, side-effect-free DB access.
  * :mod:`app.intent.service`    — deterministic dedup / upsert orchestration.
  * :mod:`app.intent.keywords`   — multilingual (EN/DE) RFQ keyword dictionary.
  * :mod:`app.intent.extractors` — 4 source adapters + :class:`SignalExtractionService`.

This package contains NO external API calls, NO scoring logic and NO changes to
lead / opportunity / contact scoring. It is the foundation that Phase 16.4
(scoring redesign) will build on.
"""

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
]
