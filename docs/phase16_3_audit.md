# Phase 16.3 — Intent Aggregation Layer

**Goal.** Convert the raw `SignalEvent` ledger (Phase 16.1 ingestion + Phase 16.2
extractors) into a per-`CompanyLead` intent snapshot that downstream surfaces
(dashboards, prioritization in later phases) can read without re-aggregating.

**Status.** Implemented, tested, migration created, audit complete. Commit is
Phase 16.3 only; not pushed (per instructions).

---

## 1. Read-only audit (pre-coding)

| Artifact | Finding | Impact on Phase 16.3 |
| --- | --- | --- |
| `SignalEvent` (Phase 16.1) | Has `company_id`, signed `value` (-100..100), `confidence` (0..100), `detected_at`, `source`, `signal_type`, `is_active`. `SignalEventService.active_for_company()` returns active rows. | Perfect, ready-to-use input. No change needed. |
| `CompanyLead` | No existing columns collide with the 6 new ones. `lead_score`, `sales_priority`, `priority`, `buying_signal` are present and **must not be touched**. | Add 6 nullable columns only. |
| Scoring utilities | `app/conversion/intent.py` holds `BASE_POINTS`/`score_reply`; not reused (different purpose). Phase 16.3 defines its own deterministic math. | Self-contained aggregator. |
| Migration chain | Head = `0038_phase16_signal_event`, `down_revision = 0037_phase15_opportunity_attribution`, single head. | New `0039` sets `down_revision = "0038_phase16_signal_event"`. |

**Conclusion:** No schema change to existing tables beyond adding 6 nullable
columns; no new model relationships; reuse the existing `SignalEvent` + service.

---

## 2. IntentAggregator design (`app/intent/aggregator.py`)

Pure, deterministic functions of the active signal set + `now`. No LLM, no
external API, no network.

### Inputs
Active `SignalEvent` rows for one company (`is_active == True`; the expire job
already flips stale rows to inactive).

### Outputs (6 values)
| Field | Type | Formula (deterministic) |
| --- | --- | --- |
| `buying_intent_score` | 0-100 int | Confidence-weighted average of each signal's normalized strength × a source-corroboration factor. |
| `timing_score` | 0-100 int | Mean recency across signals: `max(0, 100 - age_days × 4)`, floored at 0 after 25 days. |
| `intent_temperature` | str | Bucket of `effective = score × timing/100`: `≥70 HOT`, `≥50 WARM`, `≥30 COOL`, `>0 COLD`, `≤0 / no signals NONE`. |
| `last_signal_at` | datetime | `max(detected_at)` over active signals; `None` if none. |
| `intent_source_count` | int | Distinct `source` count. |
| `intent_sources` | list[str] | Sorted distinct source identifiers. |

### Key formulas
- **Normalized strength** of a signed `value`: `50 + (value/100) × 50` →
  value `+100` → 100, `0` → 50, `-100` → 0 (a deterrent pulls strength down).
- **Confidence weight** per signal: `confidence / 100` (default 50 if absent).
- **Source corroboration factor** `f`: `clamp(0.85 + (distinct-1) × 0.05, 0.85, 1.0)`.
  A single strong RFQ signal already scores high (floor 0.85); each extra
  distinct source nudges `f` toward 1.0. Final `buying_intent_score =
  round(clamp(base_strength × f, 0, 100))`.
- **Empty case:** all zeros, `intent_temperature = "NONE"`, sources `[]`.

### Why deterministic
All inputs are the signal rows + an explicit `now` argument. Same inputs → same
snapshot. This makes re-runs idempotent (the recompute script can safely
full-recompute every time).

---

## 3. Migration `0039_phase16_intent_snapshot`

- Adds 6 **nullable** columns to `company_leads` (non-destructive; snapshot
  fills incrementally via the recompute script).
- Adds 3 indexes: `ix_company_leads_buying_intent_score`,
  `ix_company_leads_intent_temperature`, `ix_company_leads_last_signal_at`.
- `down_revision = "0038_phase16_signal_event"` → single Alembic head preserved
  (`0039_phase16_intent_snapshot`).
- **SQLite compatible:** only `op.add_column` / `op.drop_column` (SQLite allows
  ADD COLUMN for nullable columns without table rewrite). Validated directly:
  add → all 6 columns present; drop → all 6 gone.

> Note: the pre-existing `0038` migration has a known SQLite `op.create_table`
> quirk when run via `alembic upgrade head` on a fresh SQLite file in this repo's
> test harness. That is unrelated to Phase 16.3 (0038 targets PostgreSQL in
> production and is already on `main`). Phase 16.3's `0039` was verified
> independently and is SQLite-safe.

---

## 4. Recompute script `scripts/recompute_intent.py`

- `recompute(db, company_ids=None, dry_run=False, limit=None)` → `(updated, skipped)`.
- Idempotent & safe to rerun: full recompute every invocation; pure-function
  aggregation.
- **Writes ONLY the six snapshot columns.** `lead.buying_intent_score`,
  `timing_score`, `intent_temperature`, `last_signal_at`, `intent_source_count`,
  `intent_sources` are assigned; `lead_score` / `sales_priority` / `priority` /
  `buying_signal` / contact ranking / Opportunity logic are never referenced.
- CLI: `--company <id>` (repeatable), `--dry-run`, `--limit`.

---

## 5. Tests `tests/test_intent_aggregator.py`

8 cases, covering the spec's required scenarios:
1. **strong recent signal** → `buying_intent_score ≥ 70`, HOT/WARM, source count 1.
2. **stale signal decay** → `timing_score == 0`, cooled to COLD.
3. **multiple signal aggregation** → multi-source score > single-source; source count = 3; sources sorted.
4. **temperature classification** → HOT/WARM/COOL/COLD/NONE boundary bands.
5. **empty signal case** → all-zero, `NONE`, sources `[]`.
6. **deterrent signal** → negative value lowers score below 50.
7. **DB integration** (`db` fixture) → `aggregate_for_company` over ingested signals.
8. **hard constraint** → `recompute` populates snapshot but leaves `lead_score`,
   `sales_priority`, `priority`, `buying_signal` untouched.

---

## 6. Constraints honored

| Constraint | Status |
| --- | --- |
| Deterministic only | ✅ Pure functions of signals + `now`. |
| No LLM | ✅ None. |
| No external APIs / network | ✅ None. |
| No `lead_score` modification | ✅ Asserted by test #8. |
| No `sales_priority` modification | ✅ Asserted by test #8. |
| No contact ranking modification | ✅ Untouched. |
| No Opportunity logic change | ✅ Untouched. |
| Single Alembic head | ✅ `0039_phase16_intent_snapshot`. |
| SQLite compatible migration | ✅ `add_column`/`drop_column` only; validated. |

---

## 7. Deliverables

- `app/intent/aggregator.py` — `IntentAggregator`, `IntentSnapshot`, `aggregate_signals`, `classify_temperature`.
- `app/models/lead.py` — 6 nullable snapshot columns added.
- `app/intent/__init__.py` — exports updated.
- `migrations/versions/0039_phase16_intent_snapshot.py` — migration.
- `scripts/recompute_intent.py` — idempotent recompute.
- `tests/test_intent_aggregator.py` — 8 tests.
- `docs/phase16_3_audit.md` — this report.

**Test result:** `pytest -k "not migration and not xlsx"` — all green, 0 failures,
2 pre-existing skips (requests not installed). New file: 8/8.
