"""Email sending module — SMTP-based delivery with send tracking.

Supports generic SMTP, Gmail SMTP, and enterprise mail servers. Configuration
is read from ``app.config.settings`` (SMTP_HOST / SMTP_PORT / SMTP_USERNAME /
SMTP_PASSWORD / SMTP_FROM_EMAIL / SMTP_USE_TLS). When no SMTP config is present
the module runs in *dry-run* mode (no real email sent) which is convenient for
tests and local development — it still records the send event so the pipeline
can advance.

Connection security (Phase 6 Stage 4 / SiteGround):
  * port ``465`` → implicit SSL (``smtplib.SMTP_SSL``) — SSL/TLS from the
    first byte, no STARTTLS;
  * any other port → plain ``smtplib.SMTP`` upgraded with STARTTLS when
    ``SMTP_USE_TLS`` is set (e.g. 587 / 25).

Two layers:

* **Phase 4 Stage 5 abstraction** — :class:`EmailSender` interface
  (``send_email`` / ``validate_recipient``) with two providers:
  :class:`SmtpEmailSender` (real delivery, transport-injectable for tests) and
  :class:`MockEmailSender` (in-memory recording used when SMTP is unconfigured
  or for tests). ``get_email_sender()`` picks the right provider.

* **Legacy helpers** — ``send_email`` / ``send_message_by_id`` return a
  delivery receipt dict:
    {"success": bool, "sender": str, "recipient": str, "sent_at": str,
     "message_id": int|None, "dry_run": bool}
  and are kept for backward compatibility with the Phase 2.5 pipeline.
"""
import re
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.crud import outreach as outreach_crud
from app.crud import outreach_events as events_crud
from app.models.outreach_message import OutreachMessage

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Phase 4 Stage 5: EmailSender abstraction + providers
# ---------------------------------------------------------------------------
@dataclass
class SendReceipt:
    """Outcome of a single ``EmailSender.send_email`` delivery attempt."""

    success: bool
    recipient: str
    sender: str
    sent_at: str = ""
    message_id: Optional[int] = None
    dry_run: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "recipient": self.recipient,
            "sender": self.sender,
            "sent_at": self.sent_at,
            "message_id": self.message_id,
            "dry_run": self.dry_run,
            "error": self.error,
        }


class EmailSender(ABC):
    """Abstract email provider: validate the recipient, deliver the message."""

    from_email: str = ""

    def validate_recipient(self, email: str) -> Optional[str]:
        """Return an error message when the recipient is invalid, else None.

        A missing address and a malformed address both fail validation.
        """
        addr = (email or "").strip()
        if not addr:
            return "recipient_email is required"
        if not _EMAIL_RE.match(addr):
            return f"invalid recipient email: {addr!r}"
        return None

    @abstractmethod
    def send_email(
        self, *, subject: str, body: str, recipient: str, sender: Optional[str] = None
    ) -> SendReceipt:
        """Deliver one message and return a :class:`SendReceipt`."""


class SmtpEmailSender(EmailSender):
    """Real SMTP delivery configured from the ``SMTP_*`` environment variables.

    ``transport`` is injectable for tests (any object exposing ``starttls()`` /
    ``login()`` / ``send_message()``) so the network IO boundary stays fully
    mock-replaceable.
    """

    def __init__(self, *, transport=None):
        self.transport = transport
        self.from_email = (
            settings.smtp_from_email or settings.smtp_username or settings.smtp_user or ""
        )

    def send_email(
        self, *, subject: str, body: str, recipient: str, sender: Optional[str] = None
    ) -> SendReceipt:
        sender_addr = sender or self.from_email or "noreply@diecasting-ai-lead-hunter.local"
        sent_at = datetime.now(timezone.utc)
        try:
            email_msg = _build_message(subject, body, sender_addr, recipient)
            if self.transport is not None:
                # Injected transport — no real network connection.
                _deliver_via_transport(self.transport, email_msg)
            else:
                with open_smtp_server() as server:
                    server.login(
                        settings.smtp_username or settings.smtp_user,
                        settings.smtp_password,
                    )
                    server.send_message(email_msg)
        except Exception as exc:  # pragma: no cover - network/SMTP dependent
            return SendReceipt(
                success=False,
                recipient=recipient,
                sender=sender_addr,
                sent_at=sent_at.isoformat(),
                error=str(exc),
            )
        return SendReceipt(
            success=True,
            recipient=recipient,
            sender=sender_addr,
            sent_at=sent_at.isoformat(),
        )


class MockEmailSender(EmailSender):
    """In-memory provider: records every send, never touches the network.

    Used when SMTP is not configured (local dev / demo) and in tests. Set
    ``fail_on`` to simulate an SMTP failure and exercise error handling.
    """

    def __init__(self):
        self.sent: List[SendReceipt] = []
        self.fail_on: Optional[str] = None
        self.from_email = "noreply@mock.local"

    def send_email(
        self, *, subject: str, body: str, recipient: str, sender: Optional[str] = None
    ) -> SendReceipt:
        sent_at = datetime.now(timezone.utc)
        sender_addr = sender or self.from_email
        if self.fail_on:
            return SendReceipt(
                success=False,
                recipient=recipient,
                sender=sender_addr,
                sent_at=sent_at.isoformat(),
                dry_run=True,
                error=self.fail_on,
            )
        receipt = SendReceipt(
            success=True,
            recipient=recipient,
            sender=sender_addr,
            sent_at=sent_at.isoformat(),
            dry_run=True,
        )
        self.sent.append(receipt)
        return receipt


def get_email_sender(*, dry_run: Optional[bool] = None, transport=None) -> EmailSender:
    """Pick a provider: real SMTP when configured (and not forced to dry-run),
    otherwise the in-memory mock (records sends, reports success)."""
    if dry_run is not False and not _smtp_configured():
        return MockEmailSender()
    return SmtpEmailSender(transport=transport)


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and (settings.smtp_user or settings.smtp_username) and settings.smtp_password)


def smtp_implicit_ssl() -> bool:
    """True when the SMTP connection must use implicit SSL (port 465).

    SiteGround (and most providers offering SSL/TLS on 465) require
    ``smtplib.SMTP_SSL`` from the first byte — STARTTLS cannot upgrade a
    plain connection on that port. Ports 25 / 587 use STARTTLS instead.
    """
    return int(settings.smtp_port or 0) == 465


def open_smtp_server():
    """Open a connection to the configured SMTP server.

    Port 465 → ``smtplib.SMTP_SSL`` (implicit SSL); any other port → a plain
    ``smtplib.SMTP`` connection upgraded with STARTTLS when ``SMTP_USE_TLS``
    is set. Returns a context manager that yields the connected server.
    """
    timeout = 30
    if smtp_implicit_ssl():
        return smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout)
    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    if settings.smtp_use_tls:
        server.starttls()
    return server


def _build_message(subject: str, body: str, sender: str, recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    return msg


def send_email(
    db: Session,
    message: OutreachMessage,
    recipient_email: str,
    *,
    sender_email: Optional[str] = None,
    dry_run: Optional[bool] = None,
    transport=None,
    gate=None,
    lead=None,
    contact=None,
    force: bool = False,
) -> dict:
    """Send an ``OutreachMessage`` via SMTP and record tracking data.

    Args:
        db: SQLAlchemy session.
        message: The OutreachMessage row to send.
        recipient_email: Target email address (usually lead.contact_email).
        sender_email: Override From address (defaults to settings.smtp_user).
        dry_run: Force dry-run mode (record but don't actually send). When
            None, dry-run is enabled automatically if SMTP is not configured.
        transport: Injectable SMTP transport for tests (any object exposing
            ``starttls()`` / ``login()`` / ``send_message()``). When provided,
            it is used instead of opening a real ``smtplib.SMTP`` connection,
            giving full mock-replaceability of the IO boundary.
        gate: Optional :class:`EmailQualityGate` (or any ``BaseEmailVerifier``).
            When supplied, the recipient is screened *before* delivery; a
            blocked verdict (invalid / risky / do_not_contact) returns a
            refused receipt and no message is sent. Pass ``force=True`` to
            bypass the gate (e.g. operator override).
        lead / contact: Related ORM rows used by the gate's do_not_contact check.
        force: Bypass the quality gate entirely.

    Returns:
        Delivery receipt dict with success / dry_run / sender / recipient / sent_at.
        A refused send carries ``{"success": False, "blocked": True, ...}``.
    """
    sender = sender_email or settings.smtp_user or "noreply@diecasting-ai-lead-hunter.local"
    is_dry_run = dry_run if dry_run is not None else (not _smtp_configured())

    # --- Outreach quality gate (Phase 4 Stage 0) ---------------------------
    if gate is not None and not force:
        verdict = gate.allow_send(
            recipient_email, lead=lead, contact=contact, db=db
        )
        if verdict.is_blocked():
            return {
                "success": False,
                "blocked": True,
                "sender": sender,
                "recipient": recipient_email,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "message_id": message.id,
                "dry_run": is_dry_run,
                "error": f"quality gate blocked: {verdict.reason}",
                "verdict": verdict.to_dict(),
            }

    sent_at = datetime.now(timezone.utc)
    success = True
    error = None

    if not is_dry_run:
        try:
            email_msg = _build_message(message.subject, message.body, sender, recipient_email)
            if transport is not None:
                # Injected transport — no real network connection.
                _deliver_via_transport(transport, email_msg)
            else:
                with open_smtp_server() as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(email_msg)
        except Exception as exc:  # pragma: no cover - network/SMTP dependent
            success = False
            error = str(exc)

    # Record send event + update message tracking.
    if success:
        outreach_crud.mark_sent(
            db, message, sender=sender, recipient=recipient_email, sent_time=sent_at
        )
        events_crud.create(
            db, lead_id=message.lead_id, event_type="sent", message_id=message.id
        )
    else:
        # Leave as drafted; surface error in receipt.
        pass

    return {
        "success": success,
        "sender": sender,
        "recipient": recipient_email,
        "sent_at": sent_at.isoformat(),
        "message_id": message.id,
        "dry_run": is_dry_run,
        "error": error,
    }


def _deliver_via_transport(transport, email_msg: EmailMessage) -> None:
    """Drive an injectable SMTP-like transport (used for mocked sends)."""
    if (
        getattr(transport, "starttls", None) is not None
        and settings.smtp_use_tls
        and not smtp_implicit_ssl()
    ):
        transport.starttls()
    if getattr(transport, "login", None) is not None:
        transport.login(
            settings.smtp_username or settings.smtp_user, settings.smtp_password
        )
    transport.send_message(email_msg)


def send_message_by_id(
    db: Session, message_id: int, recipient_email: str, *, dry_run: Optional[bool] = None
) -> dict:
    """Convenience wrapper: load a message by id then send it."""
    msg = outreach_crud.get(db, message_id)
    if msg is None:
        return {"success": False, "error": "message not found", "dry_run": bool(dry_run)}
    return send_email(db, msg, recipient_email, dry_run=dry_run)
