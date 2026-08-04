"""AI analysis package (Phase 2.3 rule-based scoring + optional OpenAI)."""
from app.ai.analyzer import analyze_company_full, run_analysis
from app.ai.scoring import (
    build_analysis,
    casting_need_score,
    detect_products,
    sales_priority,
)

__all__ = [
    "run_analysis",
    "analyze_company_full",
    "build_analysis",
    "casting_need_score",
    "sales_priority",
    "detect_products",
]
