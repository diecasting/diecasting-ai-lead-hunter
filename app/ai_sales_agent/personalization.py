"""AI email personalization engine (Phase 9 AI Sales Agent).

Reuses the existing Outreach Engine's ``generate_email_from_lead`` for the
deterministic, industry / role-template baseline, then layers contact-aware
personalisation on top: a first-name greeting and an explicit recipient. When
``use_ai`` is set and an LLM provider is configured, an optional AI rewrite is
applied, guided by the contact's role-based prompt (from ``prompts``).

Two distinct paths, both honouring "reuse existing Outreach Engine" and
"support deterministic templates + optional AI enhancement":

  * Deterministic — ``use_ai=False`` (or no provider): pure template render from
    the Outreach Engine, contact-aware greeting.
  * AI-enhanced   — ``use_ai=True`` + provider: the deterministic draft is sent
    to the LLM for a natural rewrite; on any failure we keep the deterministic
    version (``used_ai`` stays ``False``).
"""
import json
from typing import Any, Dict, Optional

from app.ai_sales_agent.llm import complete_json
from app.ai_sales_agent.prompts import role_prompt
from app.contact_intelligence.titles import classify_title_category
from app.outreach.email_generator import generate_email_from_lead


def _with_greeting(opening: str, first_name: str) -> str:
    """Replace the first non-empty line of ``opening`` with a first-name greeting."""
    lines = opening.split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            lines[i] = f"Dear {first_name},"
            break
    return "\n".join(lines)


def _first_line(text: str) -> str:
    for line in (text or "").split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _ai_enhance(
    *,
    lead,
    contact,
    baseline: Dict[str, Any],
    role_category: str,
    tone: str,
) -> Optional[Dict[str, str]]:
    """Ask the LLM to refine the baseline email for this contact / role."""
    system = role_prompt(role_category) if role_category else (
        "You are an expert B2B industrial sales copywriter for a precision die "
        "casting, CNC machining and tooling manufacturer. Rewrite the supplied "
        "cold-outreach email in natural business English, keeping it specific "
        "and free of hype."
    )
    user_payload = {
        "company": lead.name or "",
        "industry": lead.industry or "",
        "materials": lead.materials or "",
        "manufacturing_process": lead.manufacturing_process or "",
        "buying_signal": lead.buying_signal or "",
        "contact_name": (contact.full_name if contact else "") or "",
        "contact_title": (
            (contact.title or contact.role) if contact else ""
        ) or "",
        "role_category": role_category,
        "tone": tone,
        "baseline_email": baseline,
    }
    data = complete_json(
        system,
        json.dumps(user_payload, ensure_ascii=False, indent=2),
        temperature=0.4,
    )
    if not data:
        return None
    return {
        "subject": str(data.get("subject") or "").strip(),
        "opening": str(data.get("opening") or "").strip(),
        "body": str(data.get("body") or "").strip(),
        "call_to_action": str(data.get("call_to_action") or "").strip(),
    }


def _merge(baseline: Dict[str, Any], enhanced: Dict[str, str]) -> Dict[str, Any]:
    """Keep AI values when non-empty; otherwise fall back to the baseline."""
    out = dict(baseline)
    for key in ("subject", "opening", "body", "call_to_action"):
        value = (enhanced.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def generate_email(
    lead,
    *,
    contact=None,
    db=None,
    use_ai: bool = True,
    tone: str = "professional",
) -> Dict[str, Any]:
    """Generate a personalised sales email for ``lead`` (a ``CompanyLead``).

    Returns a dict with keys: subject, opening, body, call_to_action, greeting,
    to_name, to_email, contact_role, role_category, prompt_role, used_ai.
    """
    # 1) Deterministic baseline from the existing Outreach Engine.
    baseline = generate_email_from_lead(db, lead, use_llm=False)

    # 2) Contact-aware personalisation.
    to_name = ""
    to_email = ""
    role_category = ""
    first_name = ""
    if contact is not None:
        to_name = contact.full_name or ""
        to_email = contact.email or ""
        title = (contact.title or contact.role) or ""
        role_category = contact.title_category or classify_title_category(title)
        first_name = (
            contact.first_name
            or (to_name.split()[0] if to_name else "")
        ).strip()
        if first_name:
            baseline["opening"] = _with_greeting(
                baseline.get("opening", ""), first_name
            )

    prompt_role = role_category or baseline.get("contact_role") or ""

    # 3) Optional AI enhancement (best-effort; never breaks the deterministic path).
    used_ai = False
    if use_ai:
        enhanced = _ai_enhance(
            lead=lead,
            contact=contact,
            baseline=baseline,
            role_category=role_category or prompt_role,
            tone=tone,
        )
        if enhanced:
            baseline = _merge(baseline, enhanced)
            used_ai = True

    baseline["greeting"] = _first_line(baseline.get("opening", ""))
    baseline["to_name"] = to_name
    baseline["to_email"] = to_email
    baseline["role_category"] = role_category or prompt_role
    baseline["prompt_role"] = prompt_role
    baseline["used_ai"] = used_ai
    return baseline
