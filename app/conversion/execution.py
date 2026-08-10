"""Conversion recommendation acceptance (Phase 15.3.3).

Turns a *human-accepted* conversion recommendation into a concrete
:class:`app.models.sales_task.SalesTask`. This is the only place in Phase 15.3
that writes a task — :meth:`app.conversion.service.ConversionService.recompute`
remains strictly read/upsert of the :class:`ConversionSignal` snapshot and
never creates tasks.

Design rules (per the Phase 15.3 audit):
  * Human-in-the-loop: the requested ``action`` must equal the lead's
    recommended ``signal.next_action`` unless ``force=True``.
  * Idempotent: an open task for the same (lead, category, recommended action)
    is returned instead of duplicated.
  * Safety actions (``stop_sequence`` / ``suppress_contact``) set
    ``lead.do_not_contact = True`` only after explicit human acceptance.
  * A ``task_created`` :class:`OutreachEvent` timeline row is appended (best
    effort, never raises).
  * No Opportunity auto-creation, no CRM automation, no ReplyAnalysis changes.

No LLM, no network, fully deterministic.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.crud import outreach_events as events_crud
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead
from app.models.recommendation import (
    REC_ACTIVE_STATUSES,
    REC_STATUS_ACCEPTED,
    REC_STATUS_COMPLETED,
    REC_STATUS_EXPIRED,
    REC_STATUS_GENERATED,
    Recommendation,
)
from app.models.sales_task import (
    SalesTask,
    TASK_STATUS_DONE,
    TASK_STATUS_OPEN,
)


# ---------------------------------------------------------------------------
# Action -> SalesTask mapping
# ---------------------------------------------------------------------------
# (category, title). ``sets_do_not_contact`` flags the two safety actions.
_ACTION_MAP = {
    "prepare_quote": ("rfq", "Prepare quotation", False),
    "send_capability_case": ("sales", "Send capability / value case", False),
    "stop_sequence": ("nurture", "Stop outreach sequence", True),
    "suppress_contact": ("review", "Suppress contact (spam)", True),
}

# Actions that the accept endpoint is allowed to receive.
SUPPORTED_ACTIONS = tuple(_ACTION_MAP.keys())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _find_open_task(
    db: Session, *, lead_id: int, action: str
) -> Optional[SalesTask]:
    """Return an existing OPEN task for the same (lead, conversion_action).

    Replaces the earlier description-based match so that a task created by the
    Phase 10 reply flow (tagged with ``conversion_action``) and one accepted via
    the Phase 15.3.3 endpoint collapse into a single open task.
    """
    return (
        db.query(SalesTask)
        .filter(
            SalesTask.company_id == lead_id,
            SalesTask.conversion_action == action,
            SalesTask.status == TASK_STATUS_OPEN,
        )
        .first()
    )


def create_task_from_recommendation(
    db: Session,
    lead: CompanyLead,
    signal: ConversionSignal,
    action: str,
    *,
    force: bool = False,
    recommendation: Optional[Recommendation] = None,
) -> Tuple[SalesTask, bool]:
    """Create (or return existing) SalesTask from a human-accepted recommendation.

    Returns ``(task, already_exists)``.

    When ``recommendation`` is supplied (the accepted :class:`Recommendation`),
    the created task id is stamped onto ``recommendation.sales_task_id`` so the
    recommendation keeps a traceable link to the task it spawned (Phase 15.4.2).
    The recommendation's ``status`` / ``accepted_at`` are set by the caller's
    accept flow — this function only writes the task link.

    Raises
    ------
    ValueError
        If ``action`` is not a supported recommendation, or if it differs from
        ``signal.next_action`` and ``force`` is False.
    """
    if action not in _ACTION_MAP:
        raise ValueError(
            f"Unsupported action '{action}'. Supported: {', '.join(SUPPORTED_ACTIONS)}"
        )

    recommended = signal.next_action
    if action != recommended and not force:
        raise ValueError(
            f"Requested action '{action}' differs from recommended "
            f"'{recommended}'. Pass force=true to override."
        )

    category, title, sets_do_not_contact = _ACTION_MAP[action]

    # Idempotency: reuse an open task tagged with the same conversion action
    # (covers both reply-driven and previously-accepted tasks).
    existing = _find_open_task(db, lead_id=lead.id, action=action)
    if existing is not None:
        # Keep the recommendation linked even when we reuse an existing task.
        if recommendation is not None and recommendation.sales_task_id is None:
            recommendation.sales_task_id = existing.id
            db.add(recommendation)
            db.commit()
        return existing, True

    task = SalesTask(
        company_id=lead.id,
        title=title,
        description=(
            f"Accepted conversion recommendation {action} "
            f"(signal lead_id={lead.id})."
        ),
        priority=signal.next_action_priority or "medium",
        status=TASK_STATUS_OPEN,
        category=category,
        conversion_action=action,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Phase 15.4.2: close the loop — link the accepted recommendation to the task.
    if recommendation is not None:
        recommendation.sales_task_id = task.id
        db.add(recommendation)
        db.commit()

    # Safety actions confirm the opt-out only after explicit human acceptance.
    if sets_do_not_contact:
        lead.do_not_contact = True
        lead.last_activity_time = _utcnow()
        db.add(lead)
        db.commit()

    # Timeline: best-effort, isolated.
    try:
        events_crud.create(db, lead_id=lead.id, event_type="task_created")
    except Exception:
        pass

    return task, False


# ---------------------------------------------------------------------------
# Phase 15.4.2: Recommendation lifecycle closure helpers
# ---------------------------------------------------------------------------
def mark_recommendation_completed(
    db: Session,
    *,
    recommendation_id: Optional[int] = None,
    sales_task_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
) -> Optional[Recommendation]:
    """Mark a recommendation ``completed`` (and stamp ``completed_at``).

    Locates the target recommendation by one of ``recommendation_id``,
    ``sales_task_id`` (the task spawned by accept), or ``opportunity_id``
    (a downstream deal). Returns the closed recommendation, or ``None`` if no
    matching active recommendation was found. Best-effort: only transitions
    recommendations that are still ``accepted``/``generated``.

    This is a pure lifecycle writer — it does NOT create tasks, opportunities,
    or quotes, and does not touch the outreach send path.
    """
    q = db.query(Recommendation)
    if recommendation_id is not None:
        q = q.filter(Recommendation.id == recommendation_id)
    elif sales_task_id is not None:
        q = q.filter(Recommendation.sales_task_id == sales_task_id)
    elif opportunity_id is not None:
        q = q.filter(Recommendation.opportunity_id == opportunity_id)
    else:
        return None

    rec = q.filter(Recommendation.status.in_(REC_ACTIVE_STATUSES)).first()
    if rec is None:
        return None
    rec.status = REC_STATUS_COMPLETED
    rec.completed_at = _utcnow()
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def expire_stale_recommendations(
    db: Session, *, company_id: int
) -> int:
    """Expire ``generated`` recommendations superseded by a newer one.

    For each (company_id, action) pair, all but the most-recent ``generated``
    recommendation are flipped to ``expired`` (with ``expired_at``) so that only
    the latest suggestion remains active. Recommendations already ``accepted`` /
    ``completed`` are left untouched (they represent taken action).

    Returns the number of recommendations expired.
    """
    latest = (
        db.query(Recommendation)
        .filter(
            Recommendation.company_id == company_id,
            Recommendation.status == REC_STATUS_GENERATED,
        )
        .order_by(Recommendation.id.desc())
        .all()
    )
    # Keep one (the highest id) per (company_id, action) group.
    keep_ids = set()
    seen_actions = set()
    for rec in latest:
        key = (company_id, rec.action)
        if key not in seen_actions:
            seen_actions.add(key)
            keep_ids.add(rec.id)

    to_expire = [
        rec
        for rec in latest
        if rec.id not in keep_ids
    ]
    now = _utcnow()
    for rec in to_expire:
        rec.status = REC_STATUS_EXPIRED
        rec.expired_at = now
        db.add(rec)
    if to_expire:
        db.commit()
    return len(to_expire)
