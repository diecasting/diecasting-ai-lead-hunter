"""Title classification (Phase 8.5 Contact Intelligence Engine).

Maps a free-text job title (e.g. "Purchasing Manager", "CEO", "Quality
Engineer") to:

* a **category** — which function the person sits in (procurement, engineering,
  executive, operations, sales, finance, other); and
* a **seniority tier** — executive / senior / mid / junior / unknown.

The heuristics are pure, deterministic keyword maps so they are trivially
unit-testable and need no network or LLM. They intentionally favour
procurement / purchasing signals, because that is the function most relevant
to a die-casting sales motion.
"""
from typing import Tuple

# ---------------------------------------------------------------------------
# Category keyword maps (matched case-insensitively, as substrings)
# ---------------------------------------------------------------------------
_PROCUREMENT_KW = [
    "purchasing", "procurement", "buyer", "sourcing", "source",
    "supply chain", "supply-chain", "commodity", "vendor", "supplier",
    "materials manager", "expediter", "expediting",
]

_ENGINEERING_KW = [
    "engineer", "engineering", "technical", "r&d", "research",
    "design", "tooling", "tool", "manufacturing", "production",
    "quality", "process", "cad", "cam", "mechanical", "industrial",
]

_EXECUTIVE_KW = [
    "ceo", "cto", "coo", "cfo", "cio", "chief", "founder", "co-founder",
    "owner", "president", "vice president", "vp", "partner", "chairman",
    "managing director", "principal", "gm", "general manager",
    "head of", "director",
]

_OPERATIONS_KW = [
    "operations", "plant", "facility", "factory", "ops",
    "logistics", "warehouse", "maintenance", "store", "shift",
]

_SALES_KW = [
    "sales", "business development", "bd", "account", "marketing",
    "commercial", "revenue", "channel",
]

_FINANCE_KW = [
    "finance", "financial", "accountant", "accounting", "treasury",
    "controller", "audit",
]


def _has(text: str, keywords) -> bool:
    low = (text or "").lower()
    return any(kw in low for kw in keywords)


def classify_title_category(title: str) -> str:
    """Return the functional category for ``title`` (defaults to ``other``)."""
    if not title:
        return "other"
    # Order matters: check the most specific / highest-signal first, but keep a
    # stable priority so a title like "VP of Sales" lands in sales, not exec.
    if _has(title, _SALES_KW):
        return "sales"
    if _has(title, _FINANCE_KW):
        return "finance"
    if _has(title, _OPERATIONS_KW):
        return "operations"
    if _has(title, _PROCUREMENT_KW):
        return "procurement"
    if _has(title, _ENGINEERING_KW):
        return "engineering"
    if _has(title, _EXECUTIVE_KW):
        return "executive"
    return "other"


def detect_seniority(title: str) -> str:
    """Return a seniority tier for ``title`` (defaults to ``unknown``)."""
    if not title:
        return "unknown"
    low = title.lower()
    # Executive: C-level, founders, owners, partners, directors, heads, VPs.
    if any(
        kw in low
        for kw in (
            "ceo", "cto", "coo", "cfo", "cio", "chief", "founder",
            "co-founder", "owner", "president", "vice president", "vp ",
            "partner", "chairman", "managing director", "principal",
            "general manager", "head of", "director",
        )
    ):
        return "executive"
    # Senior: managers, leads, supervisors.
    if any(kw in low for kw in ("manager", "lead", "supervisor", "head ")):
        return "senior"
    # Junior / entry-level.
    if any(
        kw in low
        for kw in (
            "junior", "assistant", "intern", "trainee", "coordinator",
            "clerk", "apprentice", "entry",
        )
    ):
        return "junior"
    return "mid"


def classify_title(title: str) -> Tuple[str, str]:
    """Return ``(category, seniority)`` for a free-text ``title``."""
    return classify_title_category(title), detect_seniority(title)
