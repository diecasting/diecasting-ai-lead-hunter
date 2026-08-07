"""Contact Intelligence Engine (Phase 8.5).

Discovers individual people at a lead company, classifies their job titles,
scores them by purchasing-decision relevance and exposes them via the API.

Sub-modules:
* ``titles``    — job-title classification (category + seniority)
* ``scoring``   — purchasing-priority scoring
* ``extractor`` — website contact crawler (reuses app.crawler.contact_extractor)
* ``crud``      — Contact upsert / intelligence persistence
* ``service``   — orchestration (discover, classify, score, prioritise)
"""
from app.contact_intelligence import crud, extractor, scoring, service, titles

__all__ = ["crud", "extractor", "scoring", "service", "titles"]
