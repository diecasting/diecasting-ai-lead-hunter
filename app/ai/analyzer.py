"""AI analysis module.

Uses the OpenAI Chat Completions API to score and summarize a company as a
potential B2B die-casting customer lead. The model returns a strict JSON
object which we map onto the AI enrichment columns of CompanyLead.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from openai import OpenAI

from app.config import settings

SYSTEM_PROMPT = """You are a B2B sales-intelligence analyst specializing in the metal \
die-casting industry. Given structured information about a company, judge how promising \
it is as a die-casting customer lead.

Die-casting customers are typically manufacturers that need aluminum, zinc, or magnesium \
cast components: automotive, electronics, hardware, lighting, medical-device, power-tool, \
and appliance OEMs and Tier-1 suppliers.

Return a JSON object with EXACTLY these keys:
- score: integer 0-100 (higher = better fit)
- relevant: boolean (true if score >= 50)
- summary: one short paragraph (English) explaining why this company is or isn't a good lead
- signals: array of short strings describing concrete fit or buying-intent signals (empty if none)
"""


@dataclass
class LeadAnalysis:
    score: float
    relevant: bool
    summary: str
    signals: List[str]


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured; cannot run AI analysis."
        )
    return OpenAI(api_key=settings.openai_api_key)


def analyze_company(lead: dict) -> LeadAnalysis:
    """Analyze a company (provided as a dict) and return a LeadAnalysis."""
    client = _client()
    user_text = json.dumps(
        {
            "name": lead.get("name"),
            "website": lead.get("website"),
            "industry": lead.get("industry"),
            "description": lead.get("description"),
            "country": lead.get("country"),
            "employee_count": lead.get("employee_count"),
        },
        ensure_ascii=False,
        indent=2,
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    score = float(data.get("score", 0))
    score = max(0.0, min(100.0, score))
    return LeadAnalysis(
        score=score,
        relevant=bool(data.get("relevant", score >= 50)),
        summary=str(data.get("summary", "")),
        signals=list(data.get("signals", [])),
    )


def analysis_to_columns(analysis: LeadAnalysis) -> dict:
    """Map a LeadAnalysis onto the AI enrichment columns of CompanyLead."""
    return {
        "ai_score": analysis.score,
        "ai_relevant": analysis.relevant,
        "ai_summary": analysis.summary,
        "ai_signals": json.dumps(analysis.signals, ensure_ascii=False),
        "ai_analyzed_at": datetime.now(timezone.utc),
    }
