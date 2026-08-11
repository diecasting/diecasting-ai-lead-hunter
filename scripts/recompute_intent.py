"""Phase 16.3: recompute CompanyLead intent snapshots from signal_events.

Idempotent, safe-to-rerun batch job that:

  1. Loads every (or a given set of) CompanyLead.
  2. Aggregates its active SignalEvent rows via :class:`IntentAggregator`.
  3. Writes ONLY the six intent-snapshot columns on CompanyLead:
       buying_intent_score, timing_score, intent_temperature,
       last_signal_at, intent_source_count, intent_sources.

Hard guarantees:
  * **Idempotent** — re-running over the same signal state yields the same
    snapshot (the aggregator is a pure function of its inputs).
  * **Safe to rerun** — full recompute every time; no incremental drift.
  * **Does NOT modify** ``lead_score``, ``sales_priority``, ``priority``,
    ``buying_signal``, contact ranking, or any Opportunity field. Only the six
    snapshot columns above are touched.

Usage:
  python -m scripts.recompute_intent            # all companies
  python -m scripts.recompute_intent --company 12 --company 45
  python -m scripts.recompute_intent --dry-run  # compute + print, no DB write
  python -m scripts.recompute_intent --limit 100
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.intent.aggregator import IntentAggregator
from app.models.lead import CompanyLead


def _serialize_sources(snapshot) -> str:
    return json.dumps(snapshot.intent_sources, ensure_ascii=False)


def recompute(
    db,
    company_ids=None,
    dry_run=False,
    limit=None,
):
    """Recompute intent snapshots. Returns (updated, skipped) counts.

    ``company_ids`` optional iterable restricts the run. ``dry_run`` computes
    and prints but does not persist. Only the six snapshot columns are written.
    """
    agg = IntentAggregator(db)

    query = select(CompanyLead)
    if company_ids:
        query = query.where(CompanyLead.id.in_(company_ids))
    if limit is not None:
        query = query.limit(limit)
    companies = db.execute(query).scalars().all()

    updated = 0
    skipped = 0
    for lead in companies:
        snapshot = agg.aggregate_for_company(lead.id)
        if dry_run:
            print(
                f"[dry-run] company {lead.id} ({lead.name!r}): "
                f"score={snapshot.buying_intent_score} "
                f"timing={snapshot.timing_score} "
                f"temp={snapshot.intent_temperature} "
                f"sources={snapshot.intent_source_count} "
                f"last={snapshot.last_signal_at.isoformat() if snapshot.last_signal_at else None}"
            )
            skipped += 1
            continue

        # Write ONLY the six snapshot columns. Nothing else is touched.
        lead.buying_intent_score = snapshot.buying_intent_score
        lead.timing_score = snapshot.timing_score
        lead.intent_temperature = snapshot.intent_temperature
        lead.last_signal_at = snapshot.last_signal_at
        lead.intent_source_count = snapshot.intent_source_count
        lead.intent_sources = _serialize_sources(snapshot)
        updated += 1

    if not dry_run:
        db.commit()
    return updated, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Recompute intent snapshots (Phase 16.3).")
    parser.add_argument(
        "--company", type=int, action="append", default=[],
        help="Restrict to this company id (repeatable).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not persist.")
    parser.add_argument("--limit", type=int, default=None, help="Max companies to process.")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        company_ids = args.company or None
        updated, skipped = recompute(
            db, company_ids=company_ids, dry_run=args.dry_run, limit=args.limit
        )
        if args.dry_run:
            print(f"Dry run complete: {skipped} company(ies) evaluated, no writes.")
        else:
            print(f"Recompute complete: {updated} company(ies) updated.")
        return 0
    except Exception as exc:  # pragma: no cover - depends on DB availability
        db.rollback()
        print(f"[recompute_intent] ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
