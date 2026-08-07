"""E-mail pattern inference + role / personal classification (Phase 8).

Given a company domain and any known e-mail addresses, infer the naming
patterns the organisation likely uses (``first.last@``, ``first@``, …) and
generate candidate addresses for guessed contacts. Also classifies a local
part as *role* (sales@, info@) vs *personal* (john.smith@) vs *generic*.
"""
import re
from typing import Dict, List, Set

# Role / generic mailboxes — deliverable but not a named individual.
ROLE_LOCAL_PARTS: Set[str] = {
    "admin", "info", "support", "sales", "billing", "abuse", "postmaster",
    "webmaster", "noreply", "no-reply", "donotreply", "do-not-reply", "help",
    "contact", "office", "hello", "team", "marketing", "enquiries", "enquiry",
    "export", "business", "hr", "jobs", "careers", "service", "services",
    "accounts", "finance", "purchase", "purchasing", "procurement", "general",
}

# Free / personal providers — not a corporate contact.
FREE_EMAIL_DOMAINS: Set[str] = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "proton.me", "protonmail.com", "mail.com", "live.com",
    "gmx.com", "qq.com", "163.com", "126.com",
}

# A "personal" local-part looks like one or more alphabetic name tokens.
_NAME_RE = re.compile(r"^[a-z]+([._\-][a-z]+)*$")

# Canonical pattern templates (literal tokens expanded by generate_pattern_emails).
_PATTERN_FIRST_LAST = "first.last"
_PATTERN_FIRST = "first"
_PATTERN_FIRSTLAST = "firstlast"
_PATTERN_FLAST = "flast"
_PATTERN_FIRSTL = "firstl"

_DEFAULT_FALLBACK_PATTERNS = [
    _PATTERN_FIRST_LAST,
    _PATTERN_FIRST,
]


def is_role_email(local: str) -> bool:
    """True when ``local`` is a known role / generic mailbox name."""
    return local.strip().lower() in ROLE_LOCAL_PARTS


def is_free_email_domain(domain: str) -> bool:
    return domain.strip().lower() in FREE_EMAIL_DOMAINS


def classify_email_type(email: str) -> str:
    """Return ``role`` | ``personal`` | ``generic`` for ``email``."""
    local = email.split("@", 1)[0].strip().lower()
    if is_role_email(local):
        return "role"
    # A personal address looks like a name: alphabetic tokens, usually with a
    # separator or a longer single token.
    if _NAME_RE.match(local) and (
        "." in local or "_" in local or "-" in local or len(local) >= 6
    ):
        return "personal"
    return "generic"


def infer_patterns(known_emails: List[str], domain: str) -> List[str]:
    """Infer likely address templates from ``known_emails`` @ ``domain``.

    Returns a prioritised list of pattern tokens (``first.last``, ``first``,
    ``firstlast``, ``flast``, ``firstl``) that were observed in the known
    addresses. When nothing is observed, returns the two most common corporate
    fallbacks so callers can still suggest candidates.
    """
    domain = domain.lower()
    counts: Dict[str, int] = {}
    for e in known_emails or []:
        if "@" not in e:
            continue
        local, dom = e.split("@", 1)
        if dom.lower() != domain:
            continue
        local = local.lower()
        if "." in local:
            a, b = local.split(".", 1)
            if a.isalpha() and b.isalpha():
                counts[_PATTERN_FIRST_LAST] = counts.get(_PATTERN_FIRST_LAST, 0) + 1
                counts[_PATTERN_FLAST] = counts.get(_PATTERN_FLAST, 0) + 1
                counts[_PATTERN_FIRSTL] = counts.get(_PATTERN_FIRSTL, 0) + 1
        elif local.isalpha():
            counts[_PATTERN_FIRST] = counts.get(_PATTERN_FIRST, 0) + 1
            counts[_PATTERN_FIRSTLAST] = counts.get(_PATTERN_FIRSTLAST, 0) + 1

    ordered = sorted(counts.keys(), key=lambda p: (-counts[p], p))
    if not ordered:
        return list(_DEFAULT_FALLBACK_PATTERNS)
    return ordered


def generate_pattern_emails(
    patterns: List[str], first_name: str, last_name: str, domain: str = ""
) -> List[str]:
    """Expand ``patterns`` into concrete candidate addresses for a person.

    ``patterns`` is the list of tokens returned by :func:`infer_patterns`
    (e.g. ``["first.last", "first"]``). The expansion applies the longest
    composite tokens first so they are not clobbered by standalone ``first`` /
    ``last`` replacements. When ``domain`` is supplied, ``@<domain>`` is
    appended to every generated local-part.
    """
    first = (first_name or "").strip().lower()
    last = (last_name or "").strip().lower()
    if not first or not last:
        return []

    replacements = [
        (_PATTERN_FIRST_LAST, f"{first}.{last}"),
        (_PATTERN_FIRSTLAST, f"{first}{last}"),
        (_PATTERN_FLAST, f"{first[0]}{last}"),
        (_PATTERN_FIRSTL, f"{first}{last[0]}"),
        (_PATTERN_FIRST, first),
        ("last", last),
    ]

    out: List[str] = []
    seen: Set[str] = set()
    for pattern in patterns:
        cand = pattern
        for needle, repl in replacements:
            cand = cand.replace(needle, repl)
        if domain:
            cand = f"{cand}@{domain}"
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out
