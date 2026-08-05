"""Email inbox connector abstraction — Phase 6 Stage 3.

Providers:

* :class:`ImapInboxConnector` — real IMAP mailbox via the stdlib ``imaplib``
  (configured with ``IMAP_HOST`` / ``IMAP_PORT`` / ``IMAP_USERNAME`` /
  ``IMAP_PASSWORD`` / ``IMAP_USE_SSL`` / ``IMAP_FOLDER``).
* :class:`MockInboxConnector` — in-memory queue used when IMAP is not
  configured (dry-run) and in tests.

:func:`get_inbox_connector` picks the provider based on the environment.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from app.config import settings


@dataclass
class InboxMessage:
    """A parsed inbound email returned by a connector."""

    sender_email: str
    sender_name: str = ""
    subject: str = ""
    body: str = ""
    received_at: Optional[datetime] = None
    external_id: Optional[str] = None


class EmailInboxConnector(ABC):
    """Abstraction over a reply mailbox."""

    @abstractmethod
    def fetch_new_messages(self) -> List[InboxMessage]:
        """Return the new (unseen) inbound messages."""

    @abstractmethod
    def mark_processed(self, external_id: str) -> None:
        """Mark a fetched message as seen/processed in the mailbox."""

    def test_connection(self) -> dict:
        """Verify the mailbox connection (connect + authenticate + read).

        Returns a dict with at least ``ok``; providers add their own fields.
        Read-only — never marks messages as seen.
        """
        raise NotImplementedError


class MockInboxConnector(EmailInboxConnector):
    """In-memory connector with a shared class-level queue (dry-run / tests)."""

    queue: List[InboxMessage] = []
    processed: List[str] = []

    def fetch_new_messages(self) -> List[InboxMessage]:
        msgs = list(self.queue)
        self.queue = []
        return msgs

    def mark_processed(self, external_id: str) -> None:
        if external_id:
            self.processed.append(external_id)

    def test_connection(self) -> dict:
        return {
            "ok": True,
            "provider": "mock",
            "count": len(self.queue),
            "latest": [],
            "message": "Mock inbox (dry-run) — no real IMAP connection.",
        }


class ImapInboxConnector(EmailInboxConnector):
    """Real IMAP mailbox connector (stdlib imaplib)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        folder: str = "INBOX",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.folder = folder

    def _connect(self):
        import imaplib

        cls = imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
        conn = cls(self.host, self.port)
        conn.login(self.username, self.password)
        return conn

    def fetch_new_messages(self) -> List[InboxMessage]:
        from app.outreach.inbox.parser import parse_email

        conn = self._connect()
        try:
            conn.select(self.folder)
            typ, data = conn.search(None, "UNSEEN")
            msgs: List[InboxMessage] = []
            for num in (data[0] or b"").split():
                typ2, mdata = conn.fetch(num, "(RFC822)")
                raw = b""
                if mdata and mdata[0]:
                    raw = mdata[0][1]
                msgs.append(parse_email(raw, external_id=num.decode()))
            return msgs
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def mark_processed(self, external_id: str) -> None:
        if not external_id:
            return
        conn = self._connect()
        try:
            conn.select(self.folder)
            conn.store(external_id, "+FLAGS", "\\Seen")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def test_connection(self) -> dict:
        """Connect + authenticate + select INBOX, count messages and preview
        the latest 5 (sender / subject). Read-only — nothing is marked seen."""
        from app.outreach.inbox.parser import parse_email

        conn = None
        try:
            conn = self._connect()
            conn.select(self.folder)
            typ, data = conn.search(None, "ALL")
            nums = (data[0] or b"").split()
            count = len(nums)
            latest: List[dict] = []
            for num in nums[-5:]:
                typ2, mdata = conn.fetch(num, "(RFC822)")
                raw = b""
                if mdata and mdata[0]:
                    raw = mdata[0][1]
                msg = parse_email(raw, external_id=num.decode())
                latest.append(
                    {
                        "sender_email": msg.sender_email,
                        "sender_name": msg.sender_name,
                        "subject": msg.subject,
                        "received_at": (
                            msg.received_at.isoformat()
                            if msg.received_at is not None
                            else None
                        ),
                    }
                )
            return {"ok": True, "provider": "imap", "count": count, "latest": latest}
        except Exception as exc:
            return {
                "ok": False,
                "provider": "imap",
                "count": 0,
                "latest": [],
                "error": str(exc),
            }
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass


def imap_configured() -> bool:
    """True when a real IMAP mailbox is fully configured (host + creds)."""
    return bool(
        settings.imap_host and settings.imap_username and settings.imap_password
    )


def get_inbox_connector() -> EmailInboxConnector:
    """Return the configured connector (IMAP when configured, else mock)."""
    if imap_configured():
        return ImapInboxConnector(
            host=settings.imap_host,
            port=settings.imap_port,
            username=settings.imap_username,
            password=settings.imap_password,
            use_ssl=settings.imap_use_ssl,
            folder=settings.imap_folder,
        )
    return MockInboxConnector()
