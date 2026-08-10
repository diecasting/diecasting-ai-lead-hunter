# Phase 16.2 — Internal Signal Extraction Engine: Audit Report

**Date:** 2026-08-11
**Commit:** local `main` @ `ce8ce38` (Phase 15.4.2 / 16.1 already on `origin/main`); Phase 16.2 changes are **staged for a Phase-only commit, NOT pushed**.
**Parent foundation:** Phase 16.1 (`SignalEvent` model + `SignalEventService` deterministic ingestion, head `0038_phase16_signal_event`).
**Status:** ✅ Implemented, tested, committed (local only). No external APIs, no `lead_score` change, no schema change, no dashboard change.

---

## 1. Objective

Convert the **existing internal data sources** into `SignalEvent` records so the
Phase 16.1 event ledger is populated from data the system already owns — without
any new detection heuristics beyond what Phase 2.3 / 15 already provide. Phase
16.2 is the **source-adapter layer** only: it bridges records → `SignalInput` →
`SignalEventService.ingest`. It adds no scoring, no aggregation, and no outbound
behavior.

---

## 2. Read-Only Audit — Internal Signal Sources

| # | Source | Location | Shape | Bridge to `SignalEvent` |
|---|---|---|---|---|
| 1 | Crawled website text | `CompanyLead.website_content` (Text) | free text | Website extractor → `detect_buying_signal` (existing) |
| 2 | Multilingual RFQ text | `CompanyLead.website_content` (or any text) | free text | RFQ keyword extractor → `scan_keywords` (EN/DE) |
| 3 | Classified replies | `ReplyAnalysis` (one row / reply) | `intent`, `confidence_score`, `lead_id` | Reply intent bridge → `BASE_POINTS[intent]` |
| 4 | Conversion snapshot | `ConversionSignal` (one row / lead) | `intent_score`, `dominant_intent`, `lead_id` | Conversion bridge → `intent_score` |
| 5 | Legacy buying-signal | `CompanyLead.buying_signal` (Text `"HIGH (...)"`) | level + detail string | Legacy migration helper → level map |

**Reusable building blocks confirmed (no reinvention):**
- `app.ai.scoring.detect_buying_signal(text)` → `{level, matched, detail}` (English BUYING_SIGNALS). Safe import, no side effects.
- `app.conversion.intent.BASE_POINTS` → deterministic signed points per reply intent.
- `app.intent.service.SignalEventService.ingest` → deterministic SHA-1 `dedup_key` upsert.
- `app.models.signal_event` source/intent vocabularies (`SOURCE_WEBSITE_CHANGE`, `SOURCE_RFQ_KEYWORD`, `SOURCE_REPLY_INTENT`, `SOURCE_MANUAL`, `INTENT_PURCHASE`, `INTENT_DETERRENT`, `INTENT_RESEARCH`).

**Gap identified & closed:** `BUYING_SIGNALS` is English-only. Phase 16.2 adds a
dedicated multilingual (EN/DE) RFQ phrase bank in `app/intent/keywords.py`.

---

## 3. Constraints (Honored)

| Constraint | Status |
|---|---|
| No external APIs | ✅ no network / LLM calls anywhere in `keywords.py` or `extractors.py` |
| No `lead_score` changes | ✅ extractors never touch `CompanyLead`; asserted by `test_migrate_company_does_not_change_lead_score` |
| No dashboard changes | ✅ no routes / UI added |
| No schema changes unless required | ✅ **NO migration** — `SignalEvent` already supports everything (entity FKs, signed `value`, source/signal_type, `dedup_key`). Audit conclusion: no schema change needed. |
| Must use existing `SignalEvent` model | ✅ all adapters emit `SignalInput` consumed by `SignalEventService` |
| Must keep deterministic behavior | ✅ pure functions + deterministic value/confidence maps; idempotent upsert verified |

---

## 4. Deliverables

| File | Type | Purpose |
|---|---|---|
| `app/intent/keywords.py` | NEW | Multilingual (EN/DE/AUTO) RFQ phrase bank `RFQ_KEYWORDS` + `scan_keywords(text, lang)` |
| `app/intent/extractors.py` | NEW | 4 adapters (`build_*`) + `SignalExtractionService` |
| `app/intent/__init__.py` | EDIT | Package docstring + exports |
| `tests/test_signal_extractors.py` | NEW | 28 cases (scanner, all adapters, idempotent dedup, bridges, constraint) |
| `docs/phase16_2_audit.md` | NEW | This report |

No deletions. No migration file. Single head `0038` unchanged.

---

## 5. Adapter Design

All adapters are **pure functions** returning `List[SignalInput]`. Each carries a
stable `external_id` so the Phase 16.1 `dedup_key` (SHA-1 of entity scope +
source + signal_type + external_id) makes re-runs idempotent.

| Adapter | Source | signal_type | `value` | `confidence` | `intent_category` |
|---|---|---|---|---|---|
| Website (`detect_buying_signal`) | `website_change` | `website_buying_signal` | HIGH 70 / MED 40 / LOW −15 | 80 / 60 / 50 | purchase / deterrent |
| RFQ (`scan_keywords`, EN/DE) | `rfq_keyword` | `rfq_keyword` | HIGH 75 / MED 45 / LOW −15 | 85 / 65 / 50 | purchase / deterrent |
| Reply (`ReplyAnalysis`) | `reply_intent` | `reply:<intent>` | `BASE_POINTS[intent]` | `round(confidence_score)` | purchase / deterrent / research |
| Conversion (`ConversionSignal`) | `reply_intent` | `conversion_snapshot` | `intent_score` (already −100..100) | `\|score\|` (floor 50) | purchase / deterrent / research |
| Legacy (`buying_signal` str) | `manual` | `legacy_buying_signal` | HIGH 70 / MED 35 / LOW −20 | 75 / 55 / 50 | purchase / deterrent |

**Notes:**
- Reply neutrals (`BASE_POINTS == 0`, e.g. `out_of_office`, `supplier_existing`) are still recorded faithfully (`value = 0`, `intent_category = research`) so the ledger mirrors every classified reply; they never affect downstream scoring differently than before.
- Conversion `confidence` is derived from `|intent_score|` (stronger score → more confident), capped at 100, floor 50 for neutral.
- LOW-tier website/RFQ phrases (distributor / trader / wholesale / reseller) map to **negative** value (deterrent) — consistent with `BUYING_SIGNALS` semantics.

### `SignalExtractionService` methods
- `extract_website` / `extract_rfq_keywords` / `extract_reply` / `extract_conversion` / `extract_legacy` — single-source, return one `IngestResult` (or `None`).
- `migrate_company(company, lang="AUTO")` — website + multilingual RFQ + legacy for one `CompanyLead`.
- `bridge_replies_for_lead` / `bridge_conversions_for_lead` — DB-backed batch bridges.
- `migrate_all_companies` / `bridge_all_replies` / `bridge_all_conversions` — global backfill entry points (idempotent).

---

## 6. Determinism & Idempotency Verification

- `scan_keywords` is a pure substring scan; `scan_keywords(x) == scan_keywords(x)` holds (tested).
- Substring de-dup prevents double-counting (e.g. `anfrage` inside `angebotsanfrage`) — tested.
- Ingestion idempotency: `extract_website` twice over identical content → first `created=True`, second `created=False/updated=True`, exactly **one** row — tested.
- Website vs RFQ signals are distinct rows (different source) — not collapsed — tested.

---

## 7. Test Results

`tests/test_signal_extractors.py` — **28 cases, all green**, covering:
- multilingual scanner (EN/DE/AUTO, high/medium/low/none, substring de-dup, unsupported-lang fallback, determinism)
- all 4 adapters (positive / negative / neutral / empty / format parsing)
- idempotent dedup + website/rfq distinctness
- `bridge_replies_for_lead`, `bridge_conversions_for_lead`
- `migrate_company` → `lead_score` unchanged (hard constraint)
- package export surface

Full suite: `pytest -q -k "not migration and not xlsx"` — **all green** (Phase 16.1→16.2 inclusive; no regressions, single head `0038`).

---

## 8. Risks / Follow-ups

- **Overlap between website & RFQ adapters:** both can fire on the same `website_content` (English HIGH phrases appear in both banks). This is intentional and harmless — they use different `source`/`signal_type` and distinct `external_id`s, so downstream scoring can weight or de-duplicate as Phase 16.4 sees fit. No double counting within a single `source`.
- **Legacy `buying_signal` may itself have been produced by `detect_buying_signal`** on the same website content → website adapter + legacy adapter could both emit a HIGH signal for one company (different sources: `website_change` vs `manual`). Kept distinct by design for auditability of the backfill.
- **German coverage is phrase-bank only** (no lemmatization); future phases may add stemming. EN/DE cover the two primary markets; adding more languages is a pure data addition to `RFQ_KEYWORDS`.
- **No `expires_at` set** on extracted signals — they are permanent observations of historical records. Phase 16.4 / TTL policy can assign lifetimes later.

---

## 9. Commit Scope

Phase 16.2 **only**: `app/intent/keywords.py`, `app/intent/extractors.py`,
`app/intent/__init__.py`, `tests/test_signal_extractors.py`,
`docs/phase16_2_audit.md`. The pre-existing untracked `docs/phase16_1_audit.md`
is **excluded** from this commit. **No push** (per instruction).
