"""Outreach workflow — lead lifecycle state machine + automation pipeline.

Lead pipeline stages (``CompanyLead.lead_status``) — Phase 4.6 set:
    new → qualified → sent → contacted → replied → rfq → customer → closed
            ↘ sent ↗            ↘ replied ↖
                                    ↘ qualified (re-open)
                                    ↘ closed (dead/closed-lost)

The workflow module provides:
- ``valid_transitions``: allowed status transitions (state machine).
- ``can_transition`` / ``transition``: enforce valid moves.
- ``run_pipeline_for_lead``: a single-lead automation step that, given a HIGH
  priority lead, generates an email and (when approved) sends it, marking the
  lead ``sent``.
- ``run_daily_pipeline``: the APScheduler daily job — find new HIGH-priority
  leads, generate emails, create follow-up tasks.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.models.lead import CompanyLead
from app.outreach.contact_selector import select_best_contact
from app.outreach.email_generator import generate_email_from_lead
from app.outreach.email_verifier import VerificationResult
from app.outreach.followup import schedule_followups
from app.outreach.quality_gate import EmailQualityGate
from app.outreach.sender import send_email

# Allowed transitions between lead_status values (Phase 4.6 status set).
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "new": ["qualified", "sent", "closed"],
    "qualified": ["sent", "contacted", "rfq", "closed"],
    "sent": ["contacted", "replied", "closed"],
    "contacted": ["replied", "qualified", "rfq", "closed"],
    "replied": ["qualified", "rfq", "customer", "closed"],
    "rfq": ["customer", "replied", "closed"],
    "customer": ["closed", "replied"],
    "closed": [],
}

ALL_STATUSES = [
    "new",
    "contacted",
    "sent",
    "replied",
    "qualified",
    "rfq",
    "customer",
    "closed",
]


def can_transition(current: str, target: str) -> bool:
    """Return True if moving from ``current`` → ``target`` is allowed."""
    if current == target:
        return True
    return target in VALID_TRANSITIONS.get(current, [])


def transition(
    lead: CompanyLead, target: str, *, db: Optional[Session] = None
) -> CompanyLead:
    """Move a lead to ``target`` status, validating the transition.

    Updates ``last_activity_time``. If ``db`` is provided the change is
    persisted immediately; otherwise the caller must commit.
    """
    current = lead.lead_status or "new"
    if not can_transition(current, target):
        raise ValueError(
            f"Invalid lead status transition: {current} -> {target}. "
            f"Allowed: {VALID_TRANSITIONS.get(current, [])}"
        )
    lead.lead_status = target
    lead.last_activity_time = datetime.now(timezone.utc)
    if db is not None:
        db.add(lead)
        db.commit()
        db.refresh(lead)
    return lead


def select_outreach_contact(
    db: Session,
    lead: CompanyLead,
    *,
    gate: Optional["EmailQualityGate"] = None,
) -> Optional["object"]:
    """Pick the best recipient contact for ``lead`` (Phase 4 Stage 1).

    Loads the lead's extracted contacts, runs them through the contact selector
    (role-priority + verification confidence), and returns the top-ranked
    ``Contact`` (or ``None`` if the lead has no usable contact / no e-mail).

    ``gate`` (an ``EmailQualityVerifier``) is used to score each contact's
    e-mail confidence; when omitted, selection falls back to role + primary
    heuristics only.
    """
    from app.crud import contacts as contacts_crud

    contacts = contacts_crud.list_for_lead(db, lead.id)
    if not contacts:
        return None

    verify = None
    if gate is not None:
        def verify(email: str) -> VerificationResult:
            return gate.check(email)

    return select_best_contact(contacts, verify=verify)


def generate_email_for_lead(
    db: Session, lead: CompanyLead, *, use_llm: bool = True
) -> "object":
    """Generate an outreach email for a lead.

    Creates an ``outreach_messages`` draft row. The lead status is NOT changed
    by generation (the pipeline advances to ``sent`` only when the email is
    actually delivered); a ``generated`` outreach event records the step.
    """
    result = generate_email_from_lead(db, lead, use_llm=use_llm)
    msg = outreach_crud.create(
        db,
        lead_id=lead.id,
        subject=result.get("subject", f"Partnership opportunity with {lead.name}")[:500],
        body="\n\n".join(
            p for p in [result.get("opening"), result.get("body"), result.get("call_to_action")] if p
        ),
        contact_role=result.get("contact_role"),
        status="draft",
    )
    return msg


def approve_and_send(
    db: Session,
    lead: CompanyLead,
    message: "object",
    recipient_email: str,
    *,
    dry_run: bool = True,
    gate=None,
    contact=None,
    force: bool = False,
) -> dict:
    """Approve a draft email, send it, and advance the pipeline.

    The optional ``gate`` (an ``EmailQualityGate`` / ``BaseEmailVerifier``) is
    consulted before delivery; a blocked recipient returns a refused receipt and
    the pipeline is NOT advanced to ``sent``. Pass ``force=True`` to bypass.
    ``contact`` is the selected ``Contact`` (if any) used for the gate's
    ``do_not_contact`` check.

    On a successful send the lead transitions to ``sent``.

    Returns the send receipt from ``sender.send_email``.
    """
    from app.crud import contacts as contacts_crud

    # Resolve a related Contact (for the gate's do_not_contact check) when not
    # explicitly supplied: fall back to the message's tracking_token / recipient.
    if contact is None and getattr(message, "tracking_token", None):
        contact = contacts_crud.get_by_email(db, recipient_email)

    # Send (quality gate screens the recipient first)
    receipt = send_email(
        db, message, recipient_email, dry_run=dry_run, gate=gate, lead=lead,
        contact=contact, force=force,
    )
    if receipt.get("success"):
        transition(lead, "sent", db=db)
        # Schedule follow-ups relative to sent time.
        schedule_followups(db, lead, base_message_id=message.id)
    return receipt


def run_pipeline_for_lead(
    db: Session, lead: CompanyLead, *, dry_run: bool = True, use_llm: bool = False,
    gate: Optional["EmailQualityGate"] = None,
) -> dict:
    """Full automated pipeline for a single HIGH-priority lead.

    Steps: new/qualified → generate draft → send → ``sent``. Does nothing if
    the lead is already past ``new``/``qualified``.

    Recipient selection (Phase 4 Stage 1): when the lead has extracted
    ``contacts``, the best one is chosen automatically via
    :func:`select_outreach_contact` (role-priority + verification confidence);
    otherwise the legacy ``contact_email`` / ``contact_emails`` fallback is used.
    """
    report: dict = {"lead_id": lead.id, "steps": []}

    if lead.lead_status in ("new", "qualified"):
        msg = generate_email_for_lead(db, lead, use_llm=use_llm)
        report["steps"].append("generated")
        report["message_id"] = msg.id

        # Auto-approve and send (daily job context). Prefer the best extracted
        # contact; fall back to the legacy company-level e-mail.
        recipient = None
        selected = select_outreach_contact(db, lead, gate=gate)
        if selected is not None and getattr(selected, "email", None):
            recipient = selected.email
            report["selected_contact_id"] = selected.id
        else:
            recipient = lead.contact_email
            if not recipient and lead.contact_emails:
                emails = [e for e in (lead.contact_emails or []) if e]
                recipient = emails[0] if emails else None
        if not recipient:
            report["steps"].append("no_recipient")
            return report
        receipt = approve_and_send(
            db, lead, msg, recipient, dry_run=dry_run, gate=gate,
            contact=selected,
        )
        report["steps"].append("sent" if receipt.get("success") else "send_failed")
        report["receipt"] = receipt
    else:
        report["steps"].append(f"skip:{lead.lead_status}")
    return report


def run_daily_pipeline(
    db: Session, *, dry_run: bool = True, max_leads: int = 50
) -> dict:
    """APScheduler daily job: process new HIGH-priority leads end-to-end.

    Returns a summary report of how many leads were generated/sent.
    """
    from app.ai.ranking import rank_with_detail

    # Find new + not-yet-contacted HIGH priority leads.
    candidates = (
        db.query(CompanyLead)
        .filter(
            CompanyLead.sales_priority == "HIGH",
            CompanyLead.lead_status.in_(["new", "qualified"]),
        )
        .order_by(CompanyLead.id.desc())
        .limit(max_leads)
        .all()
    )

    generated = 0
    sent = 0
    gate = EmailQualityGate()
    for lead in candidates:
        try:
            report = run_pipeline_for_lead(
                db, lead, dry_run=dry_run, use_llm=False, gate=gate
            )
            if "generated" in report["steps"]:
                generated += 1
            if "sent" in report["steps"]:
                sent += 1
        except Exception:  # pragma: no cover - per-lead isolation
            continue

    return {
        "candidates": len(candidates),
        "emails_generated": generated,
        "emails_sent": sent,
        "dry_run": dry_run,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
