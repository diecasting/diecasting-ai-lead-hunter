"""AI-powered B2B sales email generator for die casting / CNC / tooling outreach.

Uses industry-specific Markdown templates + lead intelligence data to produce
personalised, technically-grounded sales emails. When OpenAI is configured the
LLM enriches the template with company-specific details and rephrases the body
in natural business English; otherwise a deterministic template render is used.

Input: Lead Intelligence JSON (company, industry, products, materials,
       manufacturing_process, buying_signal, reason)
Output: {"subject": ..., "body": ..., "opening": ..., "call_to_action": ...}
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.ai.keywords import INDUSTRIES as _ALL_INDUSTRIES
from app.config import settings
from app.outreach.contact_role_detector import detect_primary_role
from app.outreach.context import build_context

# ��─ Template directory ────────────────────────────────────────────────────
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


# ── Industry → template filename mapping ──────────────────────────────────
_INDUSTRY_TEMPLATE: Dict[str, str] = {
    "automotive": "automotive.md",
    "ev": "ev.md",
    "electric vehicle": "ev.md",
    "battery": "ev.md",
    "motor housing": "ev.md",
    "hydraulic": "hydraulic.md",
    "pump": "pump.md",
    "gearbox": "gearbox.md",
    "transmission": "gearbox.md",
    "industrial equipment": "industrial_equipment.md",
    "industrial": "industrial_equipment.md",
    "robotics": "industrial_equipment.md",
    "aerospace": "industrial_equipment.md",
    "cnc machining": "cnc.md",
    "cnc": "cnc.md",
    "machining": "cnc.md",
    "tooling": "tooling.md",
    "mold": "tooling.md",
}


# ── Role → role-specific prompt template mapping (Phase 4 Stage 2) ──────────
# Purchasing Manager: cost / supply chain / capacity
# Engineering:        tolerance / material / process
# Supplier Quality:   quality system / PPAP / certification
_ROLE_TEMPLATE: Dict[str, str] = {
    "purchasing manager": "purchasing_manager.md",
    "purchasing": "purchasing_manager.md",
    "strategic sourcing": "purchasing_manager.md",
    "strategic sourcing manager": "purchasing_manager.md",
    "procurement": "purchasing_manager.md",
    "buyer": "purchasing_manager.md",
    "engineering manager": "engineering.md",
    "engineering": "engineering.md",
    "component engineering": "engineering.md",
    "supplier quality": "supplier_quality.md",
    "supplier quality manager": "supplier_quality.md",
    "supplier development": "supplier_quality.md",
    "sqe": "supplier_quality.md",
    "quality": "supplier_quality.md",
}


def _detect_role_template(role_text: str) -> str:
    """Map a free-form role string to a role-specific template filename.

    Returns the role template filename, or "role_generic.md" as fallback.
    """
    lowered = (role_text or "").lower()
    # Longest key first so "strategic sourcing manager" beats "purchasing".
    sorted_keys = sorted(_ROLE_TEMPLATE.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in lowered:
            return _ROLE_TEMPLATE[key]
    return "role_generic.md"


def _detect_industry(industry_text: str) -> str:
    """Map a free-form industry string to a template filename.

    Returns the template filename (e.g. "ev.md", "automotive.md") or
    "industrial_equipment.md" as default.
    """
    lowered = (industry_text or "").lower()
    # Try longest match first to avoid "cnc" matching before "cnc machining"
    sorted_keys = sorted(_INDUSTRY_TEMPLATE.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in lowered:
            return _INDUSTRY_TEMPLATE[key]
    return "industrial_equipment.md"  # default fallback


def _load_template(template_name: str) -> str:
    """Load a Markdown template file, falling back to industrial_equipment."""
    path = _TEMPLATE_DIR / template_name
    if not path.exists():
        path = _TEMPLATE_DIR / "industrial_equipment.md"
    return path.read_text(encoding="utf-8")


def _extract_section(md: str, heading: str) -> str:
    """Extract the text under a Markdown heading (## Heading)."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, md, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def _fill_template(template_md: str, variables: Dict[str, str]) -> Dict[str, str]:
    """Render a Markdown template into subject / body / opening / cta sections."""
    subject = _extract_section(template_md, "Subject")
    capabilities = _extract_section(template_md, "Key Capabilities to Highlight")
    value_prop = _extract_section(template_md, "Value Proposition")
    cta = _extract_section(template_md, "Suggested Call to Action")

    # Simple variable substitution
    for var, val in variables.items():
        placeholder = "{" + var + "}"
        subject = subject.replace(placeholder, str(val))
        capabilities = capabilities.replace(placeholder, str(val))
        value_prop = value_prop.replace(placeholder, str(val))
        cta = cta.replace(placeholder, str(val))

    # Build a personalised opening
    company = variables.get("company", "your company")
    opening = f"Dear {company} Team,\n\nI hope this message finds you well. I am reaching out because we have identified {company} as a strong potential partner for our precision die casting and CNC machining services."

    # Build body from capabilities + value proposition
    body_parts = []
    if capabilities:
        body_parts.append("Our relevant capabilities include:\n\n" + capabilities)
    if value_prop:
        body_parts.append(value_prop)

    body = "\n\n".join(body_parts) if body_parts else ""

    return {
        "subject": subject.strip(),
        "opening": opening.strip(),
        "body": body.strip(),
        "call_to_action": cta.strip(),
    }


def _context_variables(context) -> Dict[str, str]:
    """Build the template variable dict from a CustomerContext.

    Surfaces company-specific signals (materials, process, procurement type,
    PDF-derived intelligence) so the rendered copy reads personalised rather
    than boilerplate.
    """
    ctx = context
    # Company-specific signal line (procurement + pdf intelligence).
    signals = []
    if ctx.materials:
        signals.append(f"materials: {ctx.materials}")
    if ctx.manufacturing_process:
        signals.append(f"process: {ctx.manufacturing_process}")
    if ctx.procurement_type:
        signals.append(f"procurement focus: {ctx.procurement_type}")
    if ctx.pdf_types:
        signals.append(f"documents: {', '.join(ctx.pdf_types)}")
    company_signals = "; ".join(signals)

    return {
        "company": ctx.company or "your company",
        "industry": ctx.industry or "",
        "country": ctx.country or "",
        "business_type": ctx.business_type or "",
        "products": ctx.products or ctx.description or "",
        "materials": ctx.materials or "",
        "manufacturing_process": ctx.manufacturing_process or "",
        "contact_role": ctx.contact_role or "",
        "buying_signal": ctx.buying_signal or "",
        "company_signals": company_signals,
        "lead_score": str(ctx.lead_score if ctx.lead_score is not None else ""),
        "priority": ctx.priority or "",
    }


def _fill_role_template(role_template_md: str, variables: Dict[str, str]) -> Dict[str, str]:
    """Render a role-specific template into subject / opening / body / cta.

    Unlike the industry template, the role template already carries a
    "Role Context" and "Key Messages" section; we surface the company-specific
    signals inside the opening and body so the message is personalised.
    """
    subject = _extract_section(role_template_md, "Subject")
    role_context = _extract_section(role_template_md, "Role Context")
    key_messages = _extract_section(role_template_md, "Key Messages to Highlight")
    cta = _extract_section(role_template_md, "Suggested Call to Action")

    company = variables.get("company", "your company")
    company_signals = variables.get("company_signals", "")

    # Personalised opening: greet by company + state why we reached this role.
    role_hint = ""
    if role_context:
        role_hint = " " + role_context.split("\n")[0].strip()
    opening = (
        f"Dear {company} Team,\n\n"
        f"I'm reaching out to your team because we specialise in precision die "
        f"casting and CNC machining that aligns with {company}'s programs."
    )
    if company_signals:
        opening += f" Based on what we know of {company} ({company_signals}), there is a clear fit for a technical and commercial discussion."

    # Body: role key messages + company-specific signals.
    body_parts = []
    if key_messages:
        body_parts.append("How we can support " + company + ":\n\n" + key_messages)
    if company_signals:
        body_parts.append(
            "Specifically for " + company + ", the relevant signals are: " + company_signals + "."
        )
    body = "\n\n".join(body_parts)

    # Variable substitution (handles {company} placeholders in subject/cta).
    for var, val in variables.items():
        placeholder = "{" + var + "}"
        subject = subject.replace(placeholder, str(val))
        cta = cta.replace(placeholder, str(val))

    return {
        "subject": subject.strip(),
        "opening": opening.strip(),
        "body": body.strip(),
        "call_to_action": cta.strip(),
    }


def _openai_email(prompt_data: Dict[str, Any]) -> Dict[str, str]:
    """Use OpenAI to generate a refined sales email from the lead intelligence."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)

    system = (
        "You are an expert B2B industrial sales copywriter for a precision "
        "die casting, CNC machining, and tooling manufacturer. Your emails "
        "are technically grounded, specific, and avoid generic marketing "
        "language. Focus on: technical capability, supplier value, and OEM "
        "cooperation. Always personalise with the recipient company's name, "
        "products, and industry. Never use phrases like 'cutting-edge', "
        "'game-changer', 'revolutionary', 'best-in-class', or 'world-class'."
    )

    user_msg = json.dumps(
        {
            "company": prompt_data.get("company", ""),
            "industry": prompt_data.get("industry", ""),
            "products": prompt_data.get("products", ""),
            "materials": prompt_data.get("materials", ""),
            "manufacturing_process": prompt_data.get("manufacturing_process", ""),
            "buying_signal": prompt_data.get("buying_signal", ""),
            "reason": prompt_data.get("reason", ""),
            "contact_role": prompt_data.get("contact_role", ""),
            "language": prompt_data.get("language", "en"),
            "template_guidance": prompt_data.get("template_guidance", ""),
        },
        ensure_ascii=False,
        indent=2,
    )

    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Write a cold outreach email for this B2B die casting prospect. "
                    f"Return a JSON object with keys: subject, opening, body, call_to_action. "
                    f"The opening should address the company by name. "
                    f"The body should reference their specific products, materials, and "
                    f"manufacturing processes. The call_to_action should propose a concrete "
                    f"next step. Use the template guidance below as a reference for key "
                    f"capabilities to highlight, but rewrite in natural business English.\n\n"
                    f"Prospect data:\n{user_msg}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )

    data = json.loads(resp.choices[0].message.content or "{}")
    return {
        "subject": str(data.get("subject", "")).strip(),
        "opening": str(data.get("opening", "")).strip(),
        "body": str(data.get("body", "")).strip(),
        "call_to_action": str(data.get("call_to_action", "")).strip(),
    }


def generate_email(
    lead_intelligence: Dict[str, Any],
    *,
    language: str = "en",
    tone: str = "professional",
    use_llm: bool = True,
    context: Any = None,
) -> Dict[str, str]:
    """Generate a personalised B2B sales outreach email.

    Args:
        lead_intelligence: The output from ``app.ai.analyzer.analyze_content``
            or a compatible dict with keys: company, industry, products,
            materials, manufacturing_process, buying_signal, reason.
        language: Target language ("en" supported; others fall back to en).
        tone: "professional", "friendly", or "direct".
        use_llm: When True and OPENAI_API_KEY is set, refine via OpenAI.
        context: Optional :class:`CustomerContext` (Phase 4 Stage 2). When
            supplied, the email is personalised with industry context, company
            signals, and role-specific messaging from the role template.

    Returns:
        Dict with keys: subject, opening, body, call_to_action, contact_role.
    """
    company = str(lead_intelligence.get("company") or "")
    industry = str(lead_intelligence.get("industry") or "")
    products = str(lead_intelligence.get("products") or "")
    materials = str(lead_intelligence.get("materials") or "")
    mfg_process = str(lead_intelligence.get("manufacturing_process") or "")
    buying_signal = str(lead_intelligence.get("buying_signal") or "")
    reason = str(lead_intelligence.get("reason") or "")
    business_type = str(lead_intelligence.get("business_type") or "")

    # Detect contact role (from context if provided, else from profile).
    if context is not None and getattr(context, "contact_role", None):
        contact_role = context.contact_role
    else:
        contact_role = detect_primary_role(
            industry=industry,
            business_type=business_type,
            buying_signal=buying_signal,
        )

    # Build the CustomerContext once (from explicit context or a thin wrapper).
    if context is None:
        ctx = build_context(
            company=company,
            industry=industry,
            country=str(lead_intelligence.get("country") or ""),
            business_type=business_type,
            products=products,
            materials=materials,
            manufacturing_process=mfg_process,
            description=str(lead_intelligence.get("description") or ""),
            contact_role=contact_role,
            buying_signal=buying_signal,
        )
    else:
        ctx = context

    variables = _context_variables(ctx)

    # --- Role-specific personalization (Stage 2) ---------------------------
    role_template_filename = _detect_role_template(contact_role)
    role_template_md = _load_template(role_template_filename)
    role_version = _fill_role_template(role_template_md, variables)

    # Industry template is still used as the company/process baseline and as
    # LLM guidance.
    template_filename = _detect_industry(industry)
    template_md = _load_template(template_filename)
    industry_version = _fill_template(template_md, variables)
    industry_version["contact_role"] = contact_role

    # Deterministic result prefers the role-specific copy when it produced a
    # non-empty body; otherwise falls back to the industry template.
    if role_version["body"]:
        deterministic = role_version
    else:
        deterministic = industry_version
    deterministic["contact_role"] = contact_role

    # Try LLM enrichment with full context (role guidance + company signals).
    if use_llm and settings.openai_api_key:
        try:
            prompt_data: Dict[str, Any] = {
                "company": company,
                "industry": industry,
                "products": products,
                "materials": materials,
                "manufacturing_process": mfg_process,
                "buying_signal": buying_signal,
                "reason": reason,
                "contact_role": contact_role,
                "language": language,
                "company_signals": variables.get("company_signals", ""),
                "template_guidance": role_template_md[:2000],
            }
            llm_result = _openai_email(prompt_data)
            result = {
                "subject": llm_result.get("subject") or deterministic["subject"],
                "opening": llm_result.get("opening") or deterministic["opening"],
                "body": llm_result.get("body") or deterministic["body"],
                "call_to_action": llm_result.get("call_to_action") or deterministic["call_to_action"],
                "contact_role": contact_role,
            }
            return result
        except Exception:
            pass  # fall back to deterministic

    return deterministic


def generate_email_from_lead(
    db,  # Session
    lead,  # CompanyLead instance
    *,
    use_llm: bool = True,
) -> Dict[str, str]:
    """Generate an email from a CompanyLead ORM object using its intelligence fields."""
    intelligence: Dict[str, Any] = {
        "company": lead.name or "",
        "industry": lead.industry or "",
        "products": lead.description or "",
        "materials": lead.materials or "",
        "manufacturing_process": lead.manufacturing_process or "",
        "buying_signal": lead.buying_signal or "",
        "reason": lead.ai_summary or "",
        "business_type": lead.business_type or "",
        "country": lead.country or "",
        "description": lead.description or "",
    }
    # Build a full CustomerContext (reads related contacts / documents when db
    # is available) so the email is role- and company-personalised.
    try:
        from app.outreach.context import build_context_from_lead

        context = build_context_from_lead(lead, db=db)
    except Exception:
        context = None
    return generate_email(intelligence, use_llm=use_llm, context=context)
