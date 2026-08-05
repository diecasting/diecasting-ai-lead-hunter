"""Match inbound emails to leads — Phase 6 Stage 3.

Matching priority:

1. **recipient match** — the sender's address equals the ``recipient_email``
   of an outreach message (strongest signal: the customer replies to the
   exact address we emailed), or the lead's ``contact_email``.
2. **thread / subject match** — the reply's normalized subject (leading
   ``Re:`` / ``Fwd:`` prefixes stripped) equals a *sent* outreach message's
   normalized subject.
3. **company domain** — the sender's email domain matches the lead's website
   hostname (subdomains allowed).

Returns ``(lead, message)`` where ``message`` may be ``None`` when the match
was found via the contact email or the website domain.
"""
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.incoming_email import IncomingEmail
from app.models.lead import CompanyLead
from app.models.outreach_message import OutreachMessage

_PREFIX_RE = re.compile(
    r"^\s*(?:fwd|fw|re|答复|转发|回复)\s*:?\s*(?:\[\d+\]\s*:?\s*)?", re.I
)


def normalize_subject(subject: str) -> str:
    """Strip repeated thread prefixes (``Re: Re: …``) and fold to lower case."""
    s = (subject or "").strip()
    while True:
        m = _PREFIX_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    return s.strip().lower()


def _website_host(website: str) -> str:
    if not website:
        return ""
    url = website if "://" in website else f"http://{website}"
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _email_domain(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    return (email.split("@")[-1] or "").strip().lower()


def _lead_by_website_domain(db: Session, domain: str) -> Optional[CompanyLead]:
    for lead in (
        db.query(CompanyLead).filter(CompanyLead.website.isnot(None)).all()
    ):
        host = _website_host(lead.website)
        if host == domain or host.endswith("." + domain):
            return lead
    return None


def match_incoming_email(
    db: Session, email: IncomingEmail
) -> Optional[Tuple[CompanyLead, Optional[OutreachMessage]]]:
    """Return the best (lead, message) match for an inbound email, or None."""
    sender = (email.sender_email or "").strip().lower()
    if not sender:
        return None

    # 1) recipient match against outreach messages (strongest signal).
    msg = (
        db.query(OutreachMessage)
        .filter(func.lower(OutreachMessage.recipient_email) == sender)
        .order_by(OutreachMessage.id.desc())
        .first()
    )
    if msg is not None and msg.lead is not None:
        return msg.lead, msg

    lead = (
        db.query(CompanyLead)
        .filter(func.lower(CompanyLead.contact_email) == sender)
        .first()
    )
    if lead is not None:
        return lead, None

    # 2) thread / subject match against sent outreach messages.
    norm = normalize_subject(email.subject)
    if norm:
        sent = (
            db.query(OutreachMessage)
            .filter(OutreachMessage.status == "sent")
            .order_by(OutreachMessage.id.desc())
            .all()
        )
        for m in sent:
            if m.lead is not None and normalize_subject(m.subject) == norm:
                return m.lead, m

    # 3) company domain: sender domain == lead website host.
    domain = _email_domain(sender)
    if domain:
        lead = _lead_by_website_domain(db, domain)
        if lead is not None:
            return lead, None

    return None
