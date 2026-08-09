"""Contact extraction (Phase 3 Stage 2).

Extracts structured people records from page HTML — the human contacts behind
a lead company — and persists them into the ``contacts`` table:

* ``name``      — person's full name
* ``title``     — job title (e.g. "Purchasing Manager")
* ``email``     — corporate e-mail (filtered for noise like the web crawler)
* ``linkedin``  — LinkedIn profile URL when present

Detection is heuristic and browser-free (regex + light HTML parsing) so it is
fully testable. Persistence is opt-in via ``extract_and_persist``.
"""
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.crawler.email_extractor import extract_and_filter
from app.crud import contacts as contacts_crud

# LinkedIn profile URLs (in/ or pub/).
_LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9_.\-]+", re.IGNORECASE
)

# A "Name Title" pattern: two capitalised words then a comma / em-dash / pipe
# followed by a job title. Loose on purpose — contact blocks are messy.
# e.g. "John Smith — Purchasing Manager"  /  "Jane Doe, Sales Director"
# The optional middle initial group is kept *before* the mandatory space + last
# name so it cannot swallow the first letter of the surname.
_CONTACT_LINE_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)"  # Name (first [middle] last)
    r"\s*(?:[-–—,|:]|\s+[-–—]\s+)\s*"             # separator
    r"([A-Za-z][A-Za-z\s/&]{2,40}?)"                 # title
    r"(?=\n|<|$|,)"                                 # end of line / tag / comma
)

# Common job-title keywords that anchor a contact block.
_TITLE_KEYWORDS = [
    "manager",
    "director",
    "engineer",
    "officer",
    "president",
    "lead",
    "head",
    "specialist",
    "buyer",
    "purchasing",
    "procurement",
    "sales",
    "business development",
    "ceo",
    "cto",
    "coo",
    "founder",
    "owner",
]


def _looks_like_title(text: str) -> bool:
    low = (text or "").lower()
    return any(kw in low for kw in _TITLE_KEYWORDS)


def extract_linkedin(html: str) -> Optional[str]:
    """Return the first LinkedIn profile URL found in ``html``, or ``None``."""
    m = _LINKEDIN_RE.search(html or "")
    return m.group(0) if m else None


def _email_for_match(html: str, m, site_domain: str) -> Optional[str]:
    """Find an e-mail *local* to the line/block that contains a contact match.

    Previously every contact was stamped with the first site-wide e-mail
    (``emails[0]``), which incorrectly associated one mailbox with every person.
    We now look only inside the matched line so each person is paired with an
    e-mail that actually appears next to their name (or ``None`` when none is).
    """
    start = html.rfind("\n", 0, m.start()) + 1
    end = html.find("\n", m.end())
    if end == -1:
        end = len(html)
    block = html[start:end]
    local = extract_and_filter(block, site_domain=site_domain)
    return local[0] if local else None


def extract_contacts(html: str, site_domain: str = "") -> List[Dict[str, Optional[str]]]:
    """Extract contact dicts ``{name, title, email, linkedin}`` from page HTML.

    The heuristics are intentionally conservative: we only emit a record when we
    have at least a name OR an e-mail, so we never create empty ``contacts`` rows.
    E-mail association is *block-scoped*: a contact only receives an e-mail when
    one appears on the same line as their name/title, never a global default.
    """
    if not html:
        return []
    domain = (url_domain(site_domain) or url_domain_from_html(html)).lower()

    # E-mails (filtered for corporate / sales intent), used as a fallback when
    # we see mailboxes but no name/title lines.
    emails = extract_and_filter(html, site_domain=domain)

    # LinkedIn profiles.
    linkedin = extract_linkedin(html)

    # Name / title lines.
    contacts: List[Dict[str, Optional[str]]] = []
    seen_names: set = set()
    associated_emails: set = set()

    for m in _CONTACT_LINE_RE.finditer(html or ""):
        name = m.group(1).strip()
        title = m.group(2).strip()
        if not _looks_like_title(title):
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        email = _email_for_match(html, m, domain)
        contacts.append(
            {
                "name": name,
                "title": title,
                "email": email,
                "linkedin": linkedin,
            }
        )
        if email:
            associated_emails.add(email)

    # Record any page-wide e-mails that were *not* co-located with a name as
    # their own bare-mailbox contacts, so discovery stays non-lossy. (Previously
    # these were incorrectly stamped as the e-mail of *every* named contact.)
    for email in emails:
        if email in associated_emails:
            continue
        contacts.append(
            {"name": None, "title": None, "email": email, "linkedin": linkedin}
        )

    # De-duplicate by (name, email).
    dedup: List[Dict[str, Optional[str]]] = []
    keys = set()
    for c in contacts:
        key = (c["name"], c["email"])
        if key in keys:
            continue
        keys.add(key)
        dedup.append(c)
    return dedup


def url_domain(hostname_or_url: str) -> str:
    from urllib.parse import urlparse

    if "://" in hostname_or_url or hostname_or_url.startswith("www."):
        return urlparse(hostname_or_url).hostname or ""
    return hostname_or_url


def url_domain_from_html(html: str) -> str:
    """Best-effort domain guess from ``href="https://x.com"`` occurrences."""
    m = re.search(r'href=["\']https?://([^/"\']+)', html or "")
    return m.group(1) if m else ""


def extract_and_persist(
    db: Session, lead_id: int, html: str, site_domain: str = ""
) -> List[Dict[str, Optional[str]]]:
    """Extract contacts from ``html`` and persist new rows into ``contacts``.

    Existing rows for the same (lead_id, email) or (lead_id, name) are skipped to
    avoid duplicates across multiple crawled pages. Returns the persisted records.
    """
    extracted = extract_contacts(html, site_domain=site_domain)
    persisted: List[Dict[str, Optional[str]]] = []
    for c in extracted:
        # Skip if we already have this person / mailbox for the lead.
        existing = contacts_crud.list_for_lead(db, lead_id)
        dup = any(
            (e.email and e.email == c["email"]) or (e.full_name and e.full_name == c["name"])
            for e in existing
        )
        if dup:
            continue
        obj = contacts_crud.create(
            db,
            lead_id=lead_id,
            full_name=c["name"],
            title=c["title"],
            email=c["email"],
        )
        persisted.append(
            {
                "name": obj.full_name,
                "title": obj.title,
                "email": obj.email,
                "linkedin": c["linkedin"],
            }
        )
    return persisted
