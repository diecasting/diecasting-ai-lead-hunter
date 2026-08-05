"""Reply Inbox Connector (Phase 6 Stage 3).

Pulls customer replies from the email inbox (IMAP provider, or an in-memory
mock when unconfigured), persists them, matches each to a lead, and feeds
them into the Reply Intelligence Engine (Phase 6 Stage 2) — which classifies
the intent and applies the CRM automation.
"""
from app.outreach.inbox.connector import (
    EmailInboxConnector,
    ImapInboxConnector,
    InboxMessage,
    MockInboxConnector,
    get_inbox_connector,
)
from app.outreach.inbox.matcher import match_incoming_email, normalize_subject
from app.outreach.inbox.parser import parse_email
from app.outreach.inbox.processor import persist_message, process_inbox

__all__ = [
    "EmailInboxConnector",
    "ImapInboxConnector",
    "MockInboxConnector",
    "InboxMessage",
    "get_inbox_connector",
    "parse_email",
    "normalize_subject",
    "match_incoming_email",
    "persist_message",
    "process_inbox",
]
