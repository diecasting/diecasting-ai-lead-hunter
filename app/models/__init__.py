"""Database models package.

Importing this module registers every ORM model on the shared declarative
``Base`` metadata, which is what Alembic's autogenerate (and ``create_all``)
reads from.
"""
from app.models.ai_analysis import AIAnalysis
from app.models.company_document import CompanyDocument
from app.models.crawl_task import CrawlTask
from app.models.lead import CompanyLead
from app.models.search_result import SearchResult

__all__ = [
    "CompanyLead",
    "SearchResult",
    "CrawlTask",
    "AIAnalysis",
    "CompanyDocument",
]
