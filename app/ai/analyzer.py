"""AI analysis module (Phase 2.3 upgrade — website content intelligence).

Combines a deterministic, rule-based scoring engine (``app.ai.scoring`` +
``app.ai.ranking``) with optional OpenAI enrichment for the natural-language
summary. The analysis produces the full Phase 2.3 intelligence payload and is
written to the ``ai_analysis`` history table; the latest values are
denormalised onto ``CompanyLead`` for fast querying / export.

Inputs (section 1)
------------------
The crawler / API may supply *structured* website content:

    {"homepage": ..., "about": ..., "products": ..., "industries": ..., "pdf_text": ...}

All sections are concatenated before scoring so signals spread across pages are
still captured. No OpenAI API key is required for the scores / priority /
materials / processes — only the English summary uses the LLM when configured.
"""
import json
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.ai.ranking import rank_with_detail
from app.ai.scoring import build_analysis
from app.config import settings
from app.crud import ai_analysis as ai_analysis_crud
from app.models.lead import CompanyLead

SYSTEM_PROMPT = """You are a B2B sales-intelligence analyst for the metal \
die-casting industry. Given structured information about a company, write:
- summary: one short paragraph (English) explaining why this company is or \
isn't a good die-casting / CNC / tooling lead
- signals: array of short strings describing concrete fit / buying-intent signals

Return a JSON object with EXACTLY these keys: {"summary": str, "signals": list[str]}.
"""


def _client():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


# Keys of the structured content dict, in the order they should be joined.
_CONTENT_KEYS = ("homepage", "about", "products", "industries", "pdf_text")


def _join_content(content: Dict[str, str]) -> str:
    parts = [str(content.get(k) or "") for k in _CONTENT_KEYS]
    return " ".join(p for p in parts if p).strip()


def analyze_content(
    content: Dict[str, str],
    *,
    company: str = "",
    country: str = "",
    industry: str = "",
    use_llm: bool = True,
) -> Dict:
    """Build the full Phase 2.3 intelligence payload from structured content.

    ``content`` is a mapping with the section keys above. The deterministic
    scores / priority / materials / processes come from ``scoring.build_analysis``;
    the LLM (when configured) only enriches the English ``ai_summary``.
    """
    text = _join_content(content)
    analysis = build_analysis(
        company=company,
        country=country,
        industry=industry,
        text=text,
    )

    if use_llm and settings.openai_api_key:
        try:
            client = _client()
            user_text = json.dumps(
                {
                    "name": company,
                    "industry": industry,
                    "country": country,
                    "content_sample": text[:2000],
                },
                ensure_ascii=False,
                indent=2,
            )
            resp = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            analysis["ai_summary"] = str(data.get("summary", ""))
            analysis["ai_signals"] = list(data.get("signals", []))
        except Exception:
            # LLM is best-effort; fall back to the rule-based reason.
            analysis.setdefault("ai_summary", analysis.get("reason", ""))
            analysis.setdefault("ai_signals", [])
    else:
        analysis.setdefault("ai_summary", analysis.get("reason", ""))
        analysis.setdefault("ai_signals", [])

    return analysis


def analyze_company_full(
    lead_dict: Dict,
    crawled_text: str = "",
    use_llm: bool = True,
) -> Dict:
    """Backward-compatible wrapper: build content from a flat lead dict.

    ``lead_dict`` keys: name, country, industry, description.
    """
    content = {
        "homepage": f"{lead_dict.get('name') or ''} {lead_dict.get('description') or ''}".strip(),
        "about": "",
        "products": crawled_text or "",
        "industries": lead_dict.get("industry") or "",
        "pdf_text": "",
    }
    return analyze_content(
        content,
        company=str(lead_dict.get("name") or ""),
        country=str(lead_dict.get("country") or ""),
        industry=str(lead_dict.get("industry") or ""),
        use_llm=use_llm,
    )


def run_analysis(
    db: Session,
    lead: CompanyLead,
    crawled_text: str = "",
) -> "object":
    """Analyse a lead, persist an ``AIAnalysis`` row, and update the lead.

    Returns the created ``AIAnalysis`` instance.
    """
    content = {
        "homepage": f"{lead.name or ''} {lead.description or ''}".strip(),
        "about": "",
        "products": crawled_text or lead.website_content or "",
        "industries": lead.industry or "",
        "pdf_text": "",
    }
    analysis = analyze_content(
        content,
        company=lead.name or "",
        country=lead.country or "",
        industry=lead.industry or "",
    )

    casting = analysis["casting_need_score"]
    cnc = analysis["cnc_need_score"]
    tooling = analysis["tooling_need_score"]
    rank = rank_with_detail(
        casting_need_score=casting, cnc_need_score=cnc, tooling_need_score=tooling
    )
    priority = rank["priority"]
    best = rank["primary_score"]

    row = ai_analysis_crud.create(
        db,
        lead_id=lead.id,
        casting_need_score=casting,
        sales_priority=priority,
        industry=analysis.get("industry"),
        products=analysis.get("products"),
        country=analysis.get("country"),
        buying_signal=analysis.get("buying_signal"),
        recommended_contact=analysis.get("recommended_contact"),
        analysis_json=analysis,
    )

    # Denormalise latest values onto the lead for fast reads / export.
    lead.casting_need_score = casting
    lead.cnc_need_score = cnc
    lead.tooling_need_score = tooling
    lead.sales_priority = priority
    lead.business_type = analysis.get("business_type")
    lead.materials = analysis.get("materials") or None
    lead.manufacturing_process = analysis.get("manufacturing_process") or None
    lead.buying_signal = analysis.get("buying_signal")
    lead.ai_score = float(best)
    lead.ai_relevant = best >= 50
    lead.ai_summary = analysis.get("ai_summary") or analysis.get("reason")
    lead.ai_signals = json.dumps(
        {
            "materials": (analysis.get("materials") or "").split(", ")
            if analysis.get("materials")
            else [],
            "processes": (analysis.get("manufacturing_process") or "").split(", ")
            if analysis.get("manufacturing_process")
            else [],
            "industries": (analysis.get("target_market") or "").split(", ")
            if analysis.get("target_market")
            else [],
            "buying_signal": analysis.get("buying_signal"),
        },
        ensure_ascii=False,
    )
    lead.ai_analyzed_at = datetime.now(timezone.utc)

    # Phase 3 Stage 3: composite lead score + priority, using the freshly
    # written need-scores, buying-signal and procurement data, plus the lead's
    # related contacts and PDF documents (when a DB session is available).
    from app.ai.lead_scoring import apply_lead_score

    apply_lead_score(lead, db=db)

    # Enrich contact e-mail if the analysis surfaced a concrete mailbox.
    rec = analysis.get("recommended_contact", "")
    if "@" in rec and not lead.contact_email:
        lead.contact_email = rec

    db.add(lead)
    db.commit()
    db.refresh(row)
    return row
