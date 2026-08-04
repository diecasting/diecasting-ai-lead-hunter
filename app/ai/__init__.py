"""AI analysis package (Phase 2.3 rule-based scoring + optional OpenAI)."""
from app.ai.analyzer import (
    analyze_company_full,
    analyze_content,
    run_analysis,
)
from app.ai.ranking import (
    primary_score,
    rank_lead,
    rank_with_detail,
    score_to_priority,
)
from app.ai.scoring import (
    build_analysis,
    build_reason,
    business_type,
    casting_need_score,
    cnc_need_score,
    detect_buying_signal,
    detect_industries,
    detect_materials,
    detect_processes,
    detect_products,
    sales_priority,
    tooling_need_score,
)

__all__ = [
    "run_analysis",
    "analyze_company_full",
    "analyze_content",
    "build_analysis",
    "build_reason",
    "casting_need_score",
    "cnc_need_score",
    "tooling_need_score",
    "sales_priority",
    "detect_materials",
    "detect_processes",
    "detect_industries",
    "detect_products",
    "detect_buying_signal",
    "business_type",
    "rank_lead",
    "rank_with_detail",
    "score_to_priority",
    "primary_score",
]
