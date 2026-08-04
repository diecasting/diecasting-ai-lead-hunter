"""E-mail extraction for the website crawler (Phase 2.2, section 3).

We extract standard ``xxx@company.com`` addresses from page text, drop obvious
noise (``example.com`` / ``test.com`` test domains, ``noreply@`` / ``support@``
/ ``privacy@`` mailboxes) and return a de-duplicated, *prioritised* list that
puts the high-intent sales mailboxes first.
"""
import re
from typing import List, Set

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Domains that are never a real corporate contact (test / placeholder).
BLOCK_DOMAINS = {"example.com", "test.com", "example.org", "localhost"}

# Mailbox local-parts we never want as a primary sales contact.
BLOCK_LOCAL = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "support",
    "privacy",
    "postmaster",
    "abuse",
    "webmaster",
    "admin",
    "root",
}

# Mailboxes ordered by sales-intent priority (highest first).
PRIORITY_LOCAL = ["sales", "export", "business", "inquiry", "contact", "info"]

# Free / personal providers — also dropped to keep leads corporate-only.
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "mail.com",
    "live.com",
    "msn.com",
    "gmx.com",
    "qq.com",
    "163.com",
    "126.com",
}


def extract_emails(text: str) -> Set[str]:
    """Return the set of all e-mail addresses found in ``text`` (lower-cased)."""
    if not text:
        return set()
    return {m.group(0).lower() for m in EMAIL_RE.finditer(text)}


def _is_noise(email: str) -> bool:
    local, _, dom = email.partition("@")
    if dom in BLOCK_DOMAINS or dom in FREE_EMAIL_DOMAINS:
        return True
    if local in BLOCK_LOCAL:
        return True
    return False


def _priority_rank(email: str) -> int:
    local, _, _ = email.partition("@")
    try:
        return PRIORITY_LOCAL.index(local)
    except ValueError:
        return len(PRIORITY_LOCAL)


def filter_emails(emails: Set[str], site_domain: str = "") -> List[str]:
    """Filter noise and return a prioritised, de-duplicated e-mail list.

    Ordering:
      1. priority mailboxes (sales/export/business/inquiry/contact/info)
      2. on-domain addresses (matching ``site_domain``)
      3. other corporate addresses
    """
    site_domain = (site_domain or "").lower()
    kept = [e for e in sorted(emails) if not _is_noise(e)]

    def sort_key(e: str):
        local, _, dom = e.partition("@")
        on_domain = dom == site_domain or dom.endswith("." + site_domain)
        # 1) on-domain addresses first, 2) then by sales-intent priority.
        return (0 if on_domain else 1, _priority_rank(e), e)

    ranked = sorted(kept, key=sort_key)
    seen = set()
    out: List[str] = []
    for e in ranked:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def extract_and_filter(text: str, site_domain: str = "") -> List[str]:
    """Convenience: extract e-mails from ``text`` then filter + prioritise."""
    return filter_emails(extract_emails(text), site_domain=site_domain)
