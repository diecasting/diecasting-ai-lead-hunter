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
from app.models.sales_task import (
    SalesTask,
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
) -> Tuple[SalesTask, bool]:
    """Create (or return existing) SalesTask from a human-accepted recommendation.

    Returns ``(task, already_exists)``.

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
