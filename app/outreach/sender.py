"""Email sending module — SMTP-based delivery with send tracking.

Supports generic SMTP, Gmail SMTP, and enterprise mail servers. Configuration
is read from ``app.config.settings`` (SMTP_HOST / SMTP_PORT / SMTP_USER /
SMTP_PASSWORD / SMTP_USE_TLS). When no SMTP config is present the module runs
in *dry-run* mode (no real email sent) which is convenient for tests and local
development — it still records the send event so the pipeline can advance.

``send_email`` returns a delivery receipt dict:
    {"success": bool, "sender": str, "recipient": str, "sent_at": str,
     "message_id": int|None, "dry_run": bool}
"""
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.crud import outreach as outreach_crud
from app.crud import outreach_events as events_crud
from app.models.outreach_message import OutreachMessage


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


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
) -> dict:
    """Send an ``OutreachMessage`` via SMTP and record tracking data.

    Args:
        db: SQLAlchemy session.
        message: The OutreachMessage row to send.
        recipient_email: Target email address (usually lead.contact_email).
        sender_email: Override From address (defaults to settings.smtp_user).
        dry_run: Force dry-run mode (record but don't actually send). When
            None, dry-run is enabled automatically if SMTP is not configured.

    Returns:
        Delivery receipt dict with success / dry_run / sender / recipient / sent_at.
    """
    sender = sender_email or settings.smtp_user or "noreply@diecasting-ai-lead-hunter.local"
    is_dry_run = dry_run if dry_run is not None else (not _smtp_configured())

    sent_at = datetime.now(timezone.utc)
    success = True
    error = None

    if not is_dry_run:
        try:
            email_msg = _build_message(message.subject, message.body, sender, recipient_email)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_use_tls:
                    server.starttls()
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


def send_message_by_id(
    db: Session, message_id: int, recipient_email: str, *, dry_run: Optional[bool] = None
) -> dict:
    """Convenience wrapper: load a message by id then send it."""
    msg = outreach_crud.get(db, message_id)
    if msg is None:
        return {"success": False, "error": "message not found", "dry_run": bool(dry_run)}
    return send_email(db, msg, recipient_email, dry_run=dry_run)
