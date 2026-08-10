"""Deterministic personalized email generator (Phase 14.2).

Renders a :class:`~app.outreach.personalization.context.PersonalizationContext`
into a structured, ready-to-send outreach draft:

  * ``subject``              -- one-line subject line
  * ``body``                 -- multi-line email body
  * ``personalization_reason`` -- human-readable explanation of what drove it
  * ``personalization_score``  -- deterministic 0-100 "how personalized" metric

No LLM, no network, no external API: the output is a pure function of the
context, so it is fully reproducible in offline unit tests. A later phase may
feed this draft (or the context) into an LLM for polishing, but this module
never calls one.
"""
from dataclasses import dataclass
from typing import List

from app.outreach.personalization.context import PersonalizationContext


@dataclass
class PersonalizedEmail:
    """Structured, render-ready outreach draft."""

    subject: str
    body: str
    personalization_reason: str
    personalization_score: int


# Each personalization signal contributes a fixed weight to the score. The
# weights sum to exactly 100 so a fully-populated context scores 100.
_SIGNAL_WEIGHTS = {
    "contact_name": 20,
    "contact_role_or_title": 15,
    "company_industry": 10,
    "company_materials": 15,
    "company_processes": 10,
    "ranking_score": 15,
    "capability_match": 10,
    "company_description": 5,
}


def _first_name(ctx: PersonalizationContext) -> str:
    name = (ctx.contact_name or "").strip()
    if not name:
        return "there"
    return name.split()[0]


def _active_signals(ctx: PersonalizationContext) -> List[str]:
    signals: List[str] = []
    if ctx.contact_name and ctx.contact_name.strip():
        signals.append("contact name")
    if ctx.contact_role or ctx.contact_title:
        signals.append("contact role/title")
    if ctx.company_industry:
        signals.append("company industry")
    if ctx.company_materials:
        signals.append("detected materials")
    if ctx.company_processes:
        signals.append("detected processes")
    if ctx.ranking_score is not None:
        signals.append("outreach ranking")
    if ctx.capability_match:
        signals.append("matched capabilities")
    if ctx.company_description:
        signals.append("company description")
    return signals


def _compute_score(ctx: PersonalizationContext) -> int:
    present = {
        "contact_name": bool(ctx.contact_name and ctx.contact_name.strip()),
        "contact_role_or_title": bool(ctx.contact_role or ctx.contact_title),
        "company_industry": bool(ctx.company_industry),
        "company_materials": bool(ctx.company_materials),
        "company_processes": bool(ctx.company_processes),
        "ranking_score": ctx.ranking_score is not None,
        "capability_match": bool(ctx.capability_match),
        "company_description": bool(ctx.company_description),
    }
    raw = sum(_SIGNAL_WEIGHTS[k] for k, on in present.items() if on)
    return max(0, min(100, raw))


def _build_subject(ctx: PersonalizationContext) -> str:
    name = _first_name(ctx)
    company = ctx.company_name or "your company"
    if name != "there":
        return f"Precision die-casting partnership for {company} — hello {name}"
    return f"Precision die-casting support for {company}"


def _build_body(ctx: PersonalizationContext) -> str:
    first = _first_name(ctx)
    company = ctx.company_name or "your company"
    industry = ctx.company_industry or "your industry"

    lines: List[str] = []
    lines.append(f"Hi {first},")
    lines.append("")

    # Opening — anchor on the contact's function when known.
    if ctx.contact_role:
        lines.append(
            f"I came across {company} in the {industry} space and noticed your "
            f"role as {ctx.contact_role}. Reaching the right person matters, so "
            f"I wanted to introduce ourselves directly."
        )
    else:
        lines.append(
            f"I came across {company} in the {industry} space and wanted to "
            f"reach out about your manufacturing needs."
        )
    lines.append("")

    # Prospect-fit — what we detected about their business.
    fit_bits: List[str] = []
    if ctx.company_materials:
        fit_bits.append("materials like " + ", ".join(ctx.company_materials))
    if ctx.company_processes:
        fit_bits.append("processes such as " + ", ".join(ctx.company_processes))
    if fit_bits:
        lines.append(
            "From what we can see, " + company + " works with "
            + " and ".join(fit_bits) + "."
        )
        lines.append("")

    # Our capability match — why we are a credible fit.
    if ctx.capability_match:
        lines.append(
            "Our die-casting base already supports "
            + "; ".join(ctx.capability_match)
            + ", which lines up well with the above."
        )
        lines.append("")
    elif ctx.capabilities:
        lines.append(
            "Our die-casting base covers a broad tonnage and material range "
            "built for automotive- and industrial-grade components."
        )
        lines.append("")

    # Prioritisation note — driven by the ranking engine.
    if ctx.ranking_score is not None:
        confidence = (ctx.ranking_confidence or "n/a").lower()
        lines.append(
            f"Based on our outreach scoring, this conversation is flagged as a "
            f"priority (ranking {ctx.ranking_score}/100, {confidence} confidence) "
            f"— so I'd welcome the chance to share how we can help."
        )
        lines.append("")

    # Soft CTA.
    lines.append(
        "Would you be open to a short call to see if we're a fit for your "
        "die-casting and CNC requirements? Happy to send a capability sheet."
    )
    lines.append("")
    lines.append("Best regards,")
    lines.append("Business Development Team")
    return "\n".join(lines)


def generate_personalized_email_prompt(
    ctx: PersonalizationContext,
) -> PersonalizedEmail:
    """Render ``ctx`` into a structured, deterministic outreach draft."""
    subject = _build_subject(ctx)
    body = _build_body(ctx)
    score = _compute_score(ctx)

    signals = _active_signals(ctx)
    if ctx.ranking_score is not None:
        ranking_note = (
            f"ranking_score {ctx.ranking_score}/100 "
            f"({ctx.ranking_confidence or 'n/a'} confidence)"
        )
        signals.append(ranking_note)
    if signals:
        reason = "Personalized using: " + "; ".join(signals) + "."
    else:
        reason = (
            "No personalization signals available — generated a generic draft "
            "(score 0)."
        )

    return PersonalizedEmail(
        subject=subject,
        body=body,
        personalization_reason=reason,
        personalization_score=score,
    )
