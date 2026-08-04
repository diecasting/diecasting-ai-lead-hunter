"""AI analysis module (Phase 2.3 upgrade).

Combines a deterministic, rule-based ``casting_need_score`` (see
``app.ai.scoring``) with optional OpenAI enrichment for the natural-language
summary. The analysis is written to the ``ai_analysis`` history table and the
latest values are denormalised onto ``CompanyLead`` for fast querying / export.

No OpenAI API key is required for the score / priority / products — only the
English summary uses the LLM when a key is configured.
"""
import json
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.ai.scoring import build_analysis, casting_need_score, sales_priority
from app.config import settings
from app.crud import ai_analysis as ai_analysis_crud
from app.models.lead import CompanyLead

SYSTEM_PROMPT = """You are a B2B sales-intelligence analyst for the metal \
die-casting industry. Given structured information about a company, write:
- summary: one short paragraph (English) explaining why this company is or \
isn't a good die-casting lead
- signals: array of short strings describing concrete fit / buying-intent signals

Return a JSON object with EXACTLY these keys: {"summary": str, "signals": list[str]}.
"""


def _client():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


def analyze_company_full(
    lead_dict: Dict,
    crawled_text: str = "",
    use_llm: bool = True,
) -> Dict:
    """Build the full Phase 2.3 analysis payload for a lead.

    ``lead_dict`` is a mapping with keys: name, country, industry, description.
    The deterministic score/priority/products come from ``scoring.build_analysis``;
    the LLM (when configured) only enriches the English summary.
    """
    text = " ".join(
        [
            str(lead_dict.get("name") or ""),
            str(lead_dict.get("industry") or ""),
            str(lead_dict.get("description") or ""),
            str(crawled_text or ""),
        ]
    )
    analysis = build_analysis(
        company=str(lead_dict.get("name") or ""),
        country=str(lead_dict.get("country") or ""),
        industry=str(lead_dict.get("industry") or ""),
        text=text,
    )

    if use_llm and settings.openai_api_key:
        try:
            client = _client()
            user_text = json.dumps(
                {
                    "name": lead_dict.get("name"),
                    "industry": lead_dict.get("industry"),
                    "country": lead_dict.get("country"),
                    "description": lead_dict.get("description"),
                    "crawled_text_sample": (crawled_text or "")[:2000],
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
            # LLM is best-effort; fall back to rule-based summary.
            analysis.setdefault("ai_summary", analysis.get("buying_signal", ""))
            analysis.setdefault("ai_signals", [])

    return analysis


def run_analysis(
    db: Session,
    lead: CompanyLead,
    crawled_text: str = "",
) -> "object":
    """Analyse a lead, persist an ``AIAnalysis`` row, and update the lead.

    Returns the created ``AIAnalysis`` instance.
    """
    lead_dict = {
        "name": lead.name,
        "country": lead.country,
        "industry": lead.industry,
        "description": lead.description,
    }
    # If the lead has no description yet, fall back to its name/industry only.
    analysis = analyze_company_full(lead_dict, crawled_text=crawled_text)

    score = analysis["casting_need_score"]
    priority = analysis["sales_priority"]

    row = ai_analysis_crud.create(
        db,
        lead_id=lead.id,
        casting_need_score=score,
        sales_priority=priority,
        industry=analysis.get("industry"),
        products=analysis.get("products"),
        country=analysis.get("country"),
        buying_signal=analysis.get("buying_signal"),
        recommended_contact=analysis.get("recommended_contact"),
        analysis_json=analysis,
    )

    # Denormalise latest values onto the lead for fast reads / export.
    lead.casting_need_score = score
    lead.sales_priority = priority
    lead.ai_score = float(score)
    lead.ai_relevant = score >= 50
    lead.ai_summary = analysis.get("ai_summary") or analysis.get("buying_signal")
    lead.ai_signals = json.dumps(analysis.get("ai_signals", []), ensure_ascii=False)
    lead.ai_analyzed_at = datetime.now(timezone.utc)

    # Enrich contact e-mail if the analysis surfaced a concrete mailbox.
    rec = analysis.get("recommended_contact", "")
    if "@" in rec and not lead.contact_email:
        lead.contact_email = rec

    db.add(lead)
    db.commit()
    db.refresh(row)
    return row
