"""Role-inbox generation (Phase 13.2 Contact Discovery Engine).

Generates *role* mailbox candidates for a company domain (e.g.
``purchasing@acme.com``, ``engineering@acme.com``) — the deliverable but
non-personal addresses that are the most actionable B2B die-casting outreach
targets when a named person is not published on the site.

This is deliberately distinct from :func:`app.email_discovery.patterns.
generate_pattern_emails`, which expands *personal* address templates from a
known first/last name — we do not have names here, so we generate the
organisational role inboxes instead. Both are "pattern" discovery, but they
target different address kinds.
"""
from typing import Dict, List

from app.models.contact import (
    CATEGORY_ENGINEERING,
    CATEGORY_OTHER,
    CATEGORY_PROCUREMENT,
    CATEGORY_SALES,
)

# (local-part, title_category, human role label) for the most actionable
# manufacturing-sales role mailboxes. Ordered by outreach value.
ROLE_INBOXES = [
    ("purchasing", CATEGORY_PROCUREMENT, "Purchasing"),
    ("procurement", CATEGORY_PROCUREMENT, "Procurement"),
    ("sourcing", CATEGORY_PROCUREMENT, "Sourcing"),
    ("buyer", CATEGORY_PROCUREMENT, "Buyer"),
    ("engineering", CATEGORY_ENGINEERING, "Engineering"),
    ("quality", CATEGORY_ENGINEERING, "Quality"),
    ("tooling", CATEGORY_ENGINEERING, "Tooling"),
    ("sales", CATEGORY_SALES, "Sales"),
    ("export", CATEGORY_SALES, "Export"),
    ("exports", CATEGORY_SALES, "Exports"),
    ("business", CATEGORY_SALES, "Business Development"),
    ("info", CATEGORY_OTHER, "General Enquiries"),
    ("contact", CATEGORY_OTHER, "Contact"),
    ("enquiry", CATEGORY_OTHER, "Enquiry"),
    ("enquiries", CATEGORY_OTHER, "Enquiries"),
]

# Fast lookup: local-part -> title_category.
_ROLE_CATEGORY: Dict[str, str] = {local: cat for local, cat, _ in ROLE_INBOXES}

# Fast lookup: local-part -> human role label.
_ROLE_LABEL: Dict[str, str] = {local: label for local, _, label in ROLE_INBOXES}


def generate_role_inbox_emails(domain: str) -> List[str]:
    """Return ``local@domain`` candidates for every known role mailbox.

    Returns ``[]`` when ``domain`` is empty. The list is stable / ordered so
    scoring and dedupe are deterministic.
    """
    domain = (domain or "").strip().lower()
    if not domain:
        return []
    return [f"{local}@{domain}" for local, _, _ in ROLE_INBOXES]


def role_inbox_category(email: str) -> str:
    """Return the :class:`Contact` title_category for a role mailbox.

    Looks the local-part up in :data:`ROLE_INBOXES`; falls back to
    ``CATEGORY_OTHER`` for unrecognised addresses.
    """
    if not email or "@" not in email:
        return CATEGORY_OTHER
    local = email.split("@", 1)[0].strip().lower()
    return _ROLE_CATEGORY.get(local, CATEGORY_OTHER)


def role_inbox_label(email: str) -> str:
    """Return a human-readable role label for a role mailbox (or ``""``)."""
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0].strip().lower()
    return _ROLE_LABEL.get(local, "")
