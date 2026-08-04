"""CRUD package."""
from app.crud import ai_analysis as ai_analysis_crud
from app.crud import company_documents as company_documents_crud
from app.crud import crawl_tasks as crawl_tasks_crud
from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.crud import outreach_events as outreach_events_crud
from app.crud import search_results as search_results_crud

__all__ = [
    "leads_crud",
    "search_results_crud",
    "crawl_tasks_crud",
    "ai_analysis_crud",
    "company_documents_crud",
    "outreach_crud",
    "outreach_events_crud",
]
