"""Database models package.

Importing this module registers every ORM model on the shared declarative
``Base`` metadata, which is what Alembic's autogenerate (and ``create_all``)
reads from.
"""
from app.models.ai_analysis import AIAnalysis
from app.models.company_discovery import CompanyDiscovery
from app.models.company_document import CompanyDocument
from app.models.contact import Contact
from app.models.crawl_task import CrawlTask
from app.models.discovery_job import DiscoveryJob, DiscoveryTask
from app.models.discovery_schedule import DiscoverySchedule
from app.models.email_address import EmailAddress
from app.models.email_draft import EmailDraft
from app.models.email_verification import EmailVerification
from app.models.email_tracking import EmailTracking
from app.models.followup import FollowUpSequence, OutreachFollowUp
from app.models.incoming_email import IncomingEmail
from app.models.lead import CompanyLead
from app.models.lead_source import LeadSource
from app.models.outreach_event import OutreachEvent
from app.models.outreach_message import OutreachMessage
from app.models.quora import (
    QuoraQuestion,
    ContentArticle,
    QuoraAnswer,
    BlogPost,
)
from app.models.reply_analysis import ReplyAnalysis
from app.models.reply_inbox import ReplyInbox
from app.models.search_result import SearchResult
from app.models.unsubscribe import Unsubscribe

__all__ = [
    "CompanyLead",
    "CompanyDiscovery",
    "EmailDraft",
    "DiscoveryJob",
    "DiscoveryTask",
    "DiscoverySchedule",
    "EmailAddress",
    "FollowUpSequence",
    "OutreachFollowUp",
    "IncomingEmail",
    "SearchResult",
    "CrawlTask",
    "AIAnalysis",
    "CompanyDocument",
    "OutreachMessage",
    "OutreachEvent",
    "Contact",
    "LeadSource",
    "EmailVerification",
    "EmailTracking",
    "ReplyInbox",
    "ReplyAnalysis",
    "Unsubscribe",
    "QuoraQuestion",
    "ContentArticle",
    "QuoraAnswer",
    "BlogPost",
]
