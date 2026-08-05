"""Parsing of raw inbox messages into :class:`InboxMessage` records.

Handles RFC-822 envelopes via the stdlib ``email`` package: From address
(name + email), subject (RFC-2047 decoded), and body (prefer ``text/plain``
parts, fall back to HTML parts with tags stripped).
"""
import re
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Optional

from app.outreach.inbox.connector import InboxMessage


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _extract_address(raw: str):
    """Split an address header into (name, email)."""
    name, email = "", ""
    if not raw:
        return name, email
    m = re.match(
        r"^\s*(?P<name>.*?)\s*[<（(]\s*(?P<email>[^<>()\s]+)\s*[>）)]\s*$", raw
    )
    if m:
        name = m.group("name").strip().strip('"\'')
        email = m.group("email").strip()
    else:
        email = raw.strip()
    return name, email


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(re.sub(r"[ \t]+", " ", text)).strip()


def _plain_text(msg) -> str:
    """Extract the best-effort plain-text body."""
    if msg.is_multipart():
        parts = []
        htmls = []
        for part in msg.walk():
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                parts.append(text.strip())
            elif ctype == "text/html":
                htmls.append(text)
        if parts:
            return "\n".join(parts).strip()
        if htmls:
            return _strip_html("\n".join(htmls))
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace").strip()
    except Exception:
        return payload.decode("utf-8", errors="replace").strip()


def parse_email(raw: bytes, *, external_id: Optional[str] = None) -> InboxMessage:
    """Parse raw RFC-822 bytes into an :class:`InboxMessage`."""
    msg = message_from_bytes(raw or b"")
    sender_name, sender_email = _extract_address(msg.get("From", ""))
    subject = _decode(msg.get("Subject", ""))
    body = _plain_text(msg)
    received_at = None
    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        if dt is not None:
            received_at = dt.astimezone(timezone.utc)
    except Exception:
        received_at = None
    return InboxMessage(
        external_id=external_id,
        sender_email=sender_email or "",
        sender_name=sender_name,
        subject=subject,
        body=body,
        received_at=received_at,
    )
