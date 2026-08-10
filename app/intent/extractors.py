"""Phase 16.2: Internal Signal Extraction Engine.

Converts *existing* internal data sources into :class:`SignalEvent` records,
reusing the Phase 16.1 deterministic ingestion layer
(:class:`app.intent.service.SignalEventService`). This module is the
**source-adapter** layer: every adapter is a pure function that turns one kind
of internal record / field into a list of :class:`SignalInput` payloads; the
:class:`SignalExtractionService` wraps the adapters with ingestion.

Sources covered (no external APIs, no schema change, no ``lead_score`` change):

1. **Website signal extractor** — runs the *existing* analyzer
   (:func:`app.ai.scoring.detect_buying_signal`) over
   ``CompanyLead.website_content`` and emits a ``website_change`` signal.
2. **RFQ keyword extractor** — multilingual (EN/DE, AUTO) scan via
   :func:`app.intent.keywords.scan_keywords` over any text
   (typically ``website_content``), emitting an ``rfq_keyword`` signal.
3. **Reply intent bridge** — converts :class:`ReplyAnalysis` into a
   ``reply_intent`` signal whose signed value is the deterministic
   :data:`app.conversion.intent.BASE_POINTS` for the classified intent.
4. **Conversion bridge** — converts the latest :class:`ConversionSignal`
   snapshot's signed ``intent_score`` into a ``reply_intent`` signal
   (``signal_type="conversion_snapshot"``).
5. **Legacy migration helper** — converts the legacy
   ``CompanyLead.buying_signal`` string snapshot (``"HIGH (...)"``) into a
   ``manual`` backfill signal.

All adapters are deterministic (no randomness, no network, no LLM). Re-running
extraction over the same records converges to the same ``signal_events`` state
because each payload carries a stable ``external_id`` that drives the
Phase 16.1 SHA-1 ``dedup_key`` upsert.

Value / confidence maps are *deliberately separate* from ``lead_score`` —
they describe the raw intent observation, not the aggregated fit score, so the
"No lead_score changes" constraint is honored structurally (this module never
touches ``CompanyLead``).
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.scoring import detect_buying_signal
from app.conversion.intent import BASE_POINTS
from app.intent.keywords import SUPPORTED_LANGUAGES, scan_keywords
from app.intent.service import IngestResult, SignalEventService, SignalInput
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.reply_analysis import ReplyAnalysis
from app.models.signal_event import (
    INTENT_DETERRENT,
    INTENT_PURCHASE,
    INTENT_RESEARCH,
    SOURCE_MANUAL,
    SOURCE_REPLY_INTENT,
    SOURCE_RFQ_KEYWORD,
    SOURCE_WEBSITE_CHANGE,
)

# ---------------------------------------------------------------------------
# Deterministic value / confidence maps (signed -100..100 value, 0..100 conf).
# These describe the *observation strength*, not the aggregate lead_score.
# ---------------------------------------------------------------------------
_WEBSITE_LEVEL_VALUE = {"HIGH": 70, "MEDIUM": 40, "LOW": -15}
_WEBSITE_LEVEL_CONFIDENCE = {"HIGH": 80, "MEDIUM": 60, "LOW": 50}

_RFQ_LEVEL_VALUE = {"HIGH": 75, "MEDIUM": 45, "LOW": -15}
_RFQ_LEVEL_CONFIDENCE = {"HIGH": 85, "MEDIUM": 65, "LOW": 50}

_LEGACY_LEVEL_VALUE = {"HIGH": 70, "MEDIUM": 35, "LOW": -20}
_LEGACY_LEVEL_CONFIDENCE = {"HIGH": 75, "MEDIUM": 55, "LOW": 50}

# Conversion / reply signals map their signed score directly to `value`; the
# `confidence` is derived from the magnitude of the score (stronger score =
# more confident), capped at 100, with a neutral floor of 50.
_CONVERSION_NEUTRAL_CONFIDENCE = 50


def _intent_category_for_value(value: int) -> str:
    """Map a signed signal value to an intent category (deterministic)."""
    if value > 0:
        return INTENT_PURCHASE
    if value < 0:
        return INTENT_DETERRENT
    return INTENT_RESEARCH


# ---------------------------------------------------------------------------
# Adapter 1: Website signal extractor (reuses existing analyzer)
# ---------------------------------------------------------------------------
def build_website_signals(
    company_id: int,
    website_content: Optional[str],
    detected_at: Optional[datetime] = None,
) -> List[SignalInput]:
    """Detect procurement/supplier/RFQ intent in crawled website text.

    Uses the existing, battle-tested :func:`app.ai.scoring.detect_buying_signal`
    over ``CompanyLead.website_content`` — no new detection logic, just a bridge
    into the ``SignalEvent`` ledger.
    """
    result = detect_buying_signal(website_content or "")
    level = result["level"]
    if level == "NONE":
        return []

    value = _WEBSITE_LEVEL_VALUE[level]
    confidence = _WEBSITE_LEVEL_CONFIDENCE[level]
    return [
        SignalInput(
            source=SOURCE_WEBSITE_CHANGE,
            signal_type="website_buying_signal",
            value=value,
            company_id=company_id,
            intent_category=_intent_category_for_value(value),
            confidence=confidence,
            raw_value=result["detail"],
            detected_at=detected_at,
            external_id=f"website:{company_id}",
            metadata={"level": level, "matched": result["matched"]},
        )
    ]


# ---------------------------------------------------------------------------
# Adapter 2: RFQ keyword extractor (multilingual EN/DE)
# ---------------------------------------------------------------------------
def build_rfq_keyword_signals(
    company_id: int,
    text: str,
    lang: str = "EN",
    detected_at: Optional[datetime] = None,
) -> List[SignalInput]:
    """Multilingual (EN/DE/AUTO) RFQ keyword scan over ``text``.

    Intended for the same ``CompanyLead.website_content`` (or any prospect text)
    but with German coverage and an expanded procurement phrase bank.
    """
    if lang.upper() not in SUPPORTED_LANGUAGES and lang.upper() != "AUTO":
        lang = "EN"
    scan = scan_keywords(text or "", lang=lang)
    level = scan["level"]
    if level == "NONE":
        return []

    value = _RFQ_LEVEL_VALUE[level]
    confidence = _RFQ_LEVEL_CONFIDENCE[level]
    return [
        SignalInput(
            source=SOURCE_RFQ_KEYWORD,
            signal_type="rfq_keyword",
            value=value,
            company_id=company_id,
            intent_category=_intent_category_for_value(value),
            confidence=confidence,
            raw_value=scan["detail"],
            detected_at=detected_at,
            external_id=f"rfq:{company_id}:{lang.upper()}",
            metadata={"level": level, "matched": scan["matched"], "lang": lang.upper()},
        )
    ]


# ---------------------------------------------------------------------------
# Adapter 3a: Reply intent bridge (ReplyAnalysis -> SignalEvent)
# ---------------------------------------------------------------------------
def build_reply_intent_signals(
    analysis: ReplyAnalysis,
    detected_at: Optional[datetime] = None,
) -> List[SignalInput]:
    """Convert one :class:`ReplyAnalysis` into a ``reply_intent`` signal.

    The signed ``value`` is the deterministic :data:`BASE_POINTS` for the
    classified ``intent`` (rfq_request=+45, not_interested=-30, spam=-35, ...).
    Neutral intents (value 0) are still recorded faithfully so the ledger mirrors
    every classified reply; they carry ``intent_category=research``.
    """
    intent = analysis.intent
    value = BASE_POINTS.get(intent, 0)
    confidence = (
        int(round(analysis.confidence_score))
        if analysis.confidence_score is not None
        else 50
    )
    snippet = (analysis.reply_text or "")[:500] or None
    return [
        SignalInput(
            source=SOURCE_REPLY_INTENT,
            signal_type=f"reply:{intent}",
            value=value,
            company_id=analysis.lead_id,
            intent_category=_intent_category_for_value(value),
            confidence=confidence,
            raw_value=snippet,
            detected_at=detected_at or analysis.created_at,
            external_id=f"reply:{analysis.id}",
            metadata={
                "reply_analysis_id": analysis.id,
                "message_id": analysis.message_id,
                "intent": intent,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Adapter 3b: Conversion bridge (ConversionSignal -> SignalEvent)
# ---------------------------------------------------------------------------
def build_conversion_signals(
    cs: ConversionSignal,
    detected_at: Optional[datetime] = None,
) -> List[SignalInput]:
    """Convert the latest :class:`ConversionSignal` snapshot into a signal.

    The signed ``value`` is the snapshot's ``intent_score`` (already in
    ``-100..100``). ``confidence`` is derived from ``|intent_score|`` so a
    stronger score is more confident; neutral snapshots keep a floor of 50.
    """
    if cs.intent_score is None:
        return []
    value = int(cs.intent_score)
    confidence = (
        _CONVERSION_NEUTRAL_CONFIDENCE
        if value == 0
        else max(1, min(100, abs(value)))
    )
    return [
        SignalInput(
            source=SOURCE_REPLY_INTENT,
            signal_type="conversion_snapshot",
            value=value,
            company_id=cs.lead_id,
            intent_category=_intent_category_for_value(value),
            confidence=confidence,
            raw_value=cs.dominant_intent,
            detected_at=detected_at or cs.computed_at,
            external_id=f"conversion:{cs.lead_id}",
            metadata={
                "dominant_intent": cs.dominant_intent,
                "temperature_score": cs.temperature_score,
                "temperature_label": cs.temperature_label,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Adapter 4: Legacy migration helper (CompanyLead.buying_signal -> SignalEvent)
# ---------------------------------------------------------------------------
def build_legacy_buying_signal(
    company_id: int,
    buying_signal: Optional[str],
    detected_at: Optional[datetime] = None,
) -> List[SignalInput]:
    """Backfill the legacy ``CompanyLead.buying_signal`` string into a signal.

    Legacy format (from ``app.ai.scoring.build_analysis``):
    ``"HIGH (rfq; sourcing)"`` or just ``"HIGH"``. The level is the first
    whitespace-delimited token; anything else yields no signal.
    """
    if not buying_signal:
        return []
    level = buying_signal.strip().split()[0].upper().rstrip("()")
    if level not in ("HIGH", "MEDIUM", "LOW"):
        return []

    value = _LEGACY_LEVEL_VALUE[level]
    confidence = _LEGACY_LEVEL_CONFIDENCE[level]
    return [
        SignalInput(
            source=SOURCE_MANUAL,
            signal_type="legacy_buying_signal",
            value=value,
            company_id=company_id,
            intent_category=_intent_category_for_value(value),
            confidence=confidence,
            raw_value=buying_signal,
            detected_at=detected_at,
            external_id=f"legacy:{company_id}",
            metadata={"level": level, "legacy": True},
        )
    ]


# ---------------------------------------------------------------------------
# Service: wraps the adapters with deterministic ingestion
# ---------------------------------------------------------------------------
class SignalExtractionService:
    """Bridges internal records into ``signal_events`` via Phase 16.1 ingestion.

    Every ``extract_*`` method returns an :class:`IngestResult` (or a list of
    them) — ``created`` / ``updated`` reflect the idempotent upsert, so re-running
    migration over the same data never duplicates rows.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._ingestor = SignalEventService(db)

    # --- single-source extractors (return one IngestResult) -----------------
    def extract_website(
        self,
        company_id: int,
        website_content: Optional[str],
        detected_at: Optional[datetime] = None,
    ) -> Optional[IngestResult]:
        signals = build_website_signals(
            company_id, website_content, detected_at=detected_at
        )
        if not signals:
            return None
        return self._ingestor.ingest(signals[0])

    def extract_rfq_keywords(
        self,
        company_id: int,
        text: str,
        lang: str = "EN",
        detected_at: Optional[datetime] = None,
    ) -> Optional[IngestResult]:
        signals = build_rfq_keyword_signals(
            company_id, text, lang=lang, detected_at=detected_at
        )
        if not signals:
            return None
        return self._ingestor.ingest(signals[0])

    def extract_reply(self, analysis: ReplyAnalysis) -> IngestResult:
        return self._ingestor.ingest(build_reply_intent_signals(analysis)[0])

    def extract_conversion(self, cs: ConversionSignal) -> Optional[IngestResult]:
        signals = build_conversion_signals(cs)
        if not signals:
            return None
        return self._ingestor.ingest(signals[0])

    def extract_legacy(
        self,
        company_id: int,
        buying_signal: Optional[str],
        detected_at: Optional[datetime] = None,
    ) -> Optional[IngestResult]:
        signals = build_legacy_buying_signal(
            company_id, buying_signal, detected_at=detected_at
        )
        if not signals:
            return None
        return self._ingestor.ingest(signals[0])

    # --- company-level convenience (website + rfq + legacy from CompanyLead) -
    def migrate_company(
        self, company: CompanyLead, lang: str = "AUTO"
    ) -> List[IngestResult]:
        """Extract website, multilingual RFQ and legacy signals for one company."""
        results: List[IngestResult] = []
        detected = company.updated_at  # type: ignore[assignment]
        r = self.extract_website(company.id, company.website_content, detected_at=detected)
        if r is not None:
            results.append(r)
        r = self.extract_rfq_keywords(
            company.id, company.website_content or "", lang=lang, detected_at=detected
        )
        if r is not None:
            results.append(r)
        r = self.extract_legacy(
            company.id, company.buying_signal, detected_at=company.created_at
        )
        if r is not None:
            results.append(r)
        return results

    # --- DB-backed batch bridges --------------------------------------------
    def bridge_replies_for_lead(self, lead_id: int) -> List[IngestResult]:
        analyses = (
            self.db.query(ReplyAnalysis)
            .filter(ReplyAnalysis.lead_id == lead_id)
            .all()
        )
        return [self.extract_reply(a) for a in analyses]

    def bridge_conversions_for_lead(self, lead_id: int) -> List[IngestResult]:
        rows = (
            self.db.query(ConversionSignal)
            .filter(ConversionSignal.lead_id == lead_id)
            .all()
        )
        results: List[IngestResult] = []
        for cs in rows:
            r = self.extract_conversion(cs)
            if r is not None:
                results.append(r)
        return results

    # --- global migration ----------------------------------------------------
    def migrate_all_companies(self, lang: str = "AUTO") -> List[IngestResult]:
        """Backfill every company's internal signals (website + rfq + legacy)."""
        companies = self.db.query(CompanyLead).all()
        results: List[IngestResult] = []
        for company in companies:
            results.extend(self.migrate_company(company, lang=lang))
        return results

    def bridge_all_replies(self) -> List[IngestResult]:
        analyses = self.db.query(ReplyAnalysis).all()
        return [self.extract_reply(a) for a in analyses]

    def bridge_all_conversions(self) -> List[IngestResult]:
        rows = self.db.query(ConversionSignal).all()
        results: List[IngestResult] = []
        for cs in rows:
            r = self.extract_conversion(cs)
            if r is not None:
                results.append(r)
        return results
