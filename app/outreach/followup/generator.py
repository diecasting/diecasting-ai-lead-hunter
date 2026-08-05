"""Follow-up email generation (Phase 6 Stage 1).

Renders a follow-up ``OutreachMessage`` draft from a sequence step's template,
personalised with the lead's profile (materials / process / industry) and the
contact-aware greeting from Phase 4 Stage 4.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.crud import outreach as outreach_crud
from app.models.lead import CompanyLead
from app.models.outreach_message import OutreachMessage

# Follow-up copy templates keyed by sequence ``template`` name.
_TEMPLATES: Dict[str, str] = {
    "technical_followup": (
        "We would love to walk you through our technical capabilities for "
        "{process} of {materials} components — tight tolerances, in-house "
        "tooling lead times, and quality certifications (IATF 16949 / PPAP)."
    ),
    "rfq_followup": (
        "If you are currently collecting quotes for {industry} programs, we "
        "would welcome the chance to submit a competitive proposal with "
        "transparent piece pricing and tooling amortisation."
    ),
    "value_prop_followup": (
        "As a quick recap, our value proposition: consolidated casting + CNC "
        "+ finishing under one roof, dual-source supply security, and in-house "
        "tooling for fast prototypes."
    ),
}


def _render_body(lead: CompanyLead, template: str) -> str:
    text = _TEMPLATES.get(template, _TEMPLATES["technical_followup"])
    body = text.format(
        process=(lead.manufacturing_process or "die casting"),
        materials=(lead.materials or "aluminum"),
        industry=(lead.industry or "your programs"),
    )
    greeting = "Dear Purchasing Manager,"
    try:
        from app.outreach.email_generator import _build_greeting
        from app.outreach.context import build_context_from_lead

        greeting = _build_greeting(build_context_from_lead(lead))
    except Exception:
        pass  # fall back to the generic greeting
    return f"{greeting}\n\n{body}\n\nBest regards,\nDie Casting AI Lead Hunter"


def generate_followup_email(
    db: Session,
    lead: CompanyLead,
    original_message: Optional[OutreachMessage],
    *,
    step: Dict[str, Any],
    step_number: int,
) -> OutreachMessage:
    """Create the follow-up draft message from a sequence step.

    The recipient (name + email) is carried over from the original sent
    message (or the lead's contact info) so the follow-up can be sent through
    the same pipeline.
    """
    template = step.get("template") or "technical_followup"
    subject = (
        f"Re: {original_message.subject[:400]}"
        if original_message and original_message.subject
        else f"Follow-up: partnership with {lead.name}"
    )
    body = _render_body(lead, template)

    # Best-effort quality gate (same deterministic scorer as Stage 2/3).
    quality_score = None
    gate_status = None
    try:
        from app.outreach.context import build_context_from_lead
        from app.outreach.draft_quality_gate import classify_quality_gate
        from app.outreach.email_quality import score_email_quality

        ctx = build_context_from_lead(lead, db=db)
        quality_score = score_email_quality(body, ctx).get("quality")
        gate_status = classify_quality_gate(quality_score)
    except Exception:
        pass

    recipient_name = None
    recipient_email = None
    if original_message is not None:
        recipient_name = original_message.recipient_name or None
        recipient_email = original_message.recipient_email or None
    recipient_name = recipient_name or (lead.contact_name or None)
    recipient_email = recipient_email or (lead.contact_email or None)

    return outreach_crud.create(
        db,
        lead_id=lead.id,
        subject=subject[:500],
        body=body,
        contact_role=(lead.contact_role or None)
        or (original_message.contact_role if original_message else None),
        status="draft",
        is_followup=True,
        followup_seq=step_number,
        quality_score=quality_score,
        quality_gate_status=gate_status,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
    )
