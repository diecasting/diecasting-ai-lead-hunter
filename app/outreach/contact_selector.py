"""Contact selection strategy (Phase 4 Stage 1).

Given the contacts extracted for a lead, pick the best recipient for outreach.

Priority order (the four buying-role tiers requested for Stage 1):
    1. Purchasing Manager
    2. Strategic Sourcing
    3. Supplier Quality
    4. Engineering Manager

Within / across roles, contacts are ranked by a composite score that blends:
    * role priority (higher tier = more points),
    * email confidence (from verification + role relevance),
    * primary-contact flag,
    * presence of a deliverable e-mail,
    * do_not_contact (excluded entirely).

The selector is pure (operates on a list of contacts + an optional gate/verify
function) so it is trivially unit-testable without a database.
"""
from typing import Callable, List, Optional

from app.outreach.confidence import score_email_confidence
from app.outreach.email_verifier import VerificationResult

# Role tier priority: lower number = higher priority (more points).
_ROLE_PRIORITY = {
    "purchasing manager": 0,
    "strategic sourcing": 1,
    "strategic sourcing manager": 1,
    "supplier quality": 2,
    "supplier quality manager": 2,
    "engineering manager": 3,
    "engineering": 3,
}


def role_priority(role: Optional[str]) -> int:
    """Return the priority rank of a role (0 = best). Unknown roles rank last."""
    r = (role or "").strip().lower()
    if r in _ROLE_PRIORITY:
        return _ROLE_PRIORITY[r]
    for key, rank in _ROLE_PRIORITY.items():
        if key in r:
            return rank
    return 99  # unrecognised role -> lowest priority


def _role_points(role: Optional[str]) -> int:
    """Map a role priority rank to points (best=40, worst=0)."""
    rank = role_priority(role)
    if rank <= 3:
        return 40 - rank * 10  # 40,30,20,10
    return 0


def _contact_role(contact) -> Optional[str]:
    return getattr(contact, "role", None) or getattr(contact, "title", None)


def _contact_email(contact) -> Optional[str]:
    return getattr(contact, "email", None)


def contact_confidence(
    contact,
    verify: Optional[Callable[[str], VerificationResult]] = None,
) -> int:
    """Confidence score for a single contact, optionally verified."""
    email = _contact_email(contact)
    role = _contact_role(contact)
    verification = None
    if verify is not None and email:
        try:
            verification = verify(email)
        except Exception:
            verification = None
    return score_email_confidence(
        email or "",
        verification,
        role=role,
        has_email=bool(email),
        is_primary=bool(getattr(contact, "is_primary", False)),
        do_not_contact=bool(getattr(contact, "do_not_contact", False)),
    )


def _ranking_sort_key(item):
    """Blend the Phase 14.1 outreach ``ranking_score`` with the legacy
    role/confidence ordering.

    ``item`` is a ``(contact, confidence)`` pair. When a contact carries a
    computed ``ranking_score`` it is sorted first (``group == 0``) and ranked by
    that score; contacts that have not been ranked yet fall into ``group == 1``
    and use the legacy role-priority / confidence / primary ordering. So the
    ranking engine's output is authoritative *when available*, and selection
    degrades gracefully to the pre-14.1 behaviour otherwise.
    """
    c, conf = item
    rs = getattr(c, "ranking_score", None)
    role = _contact_role(c)
    primary = -int(bool(getattr(c, "is_primary", False)))
    if rs is not None:
        # Ranking present: score dominates, legacy signals break ties.
        return (0, -rs, role_priority(role), -conf, primary)
    # Fallback: legacy role-priority / confidence / primary ordering.
    return (1, role_priority(role), -conf, primary)


def select_best_contact(
    contacts: List,
    *,
    verify: Optional[Callable[[str], VerificationResult]] = None,
    preferred_roles: Optional[List[str]] = None,
) -> Optional[object]:
    """Return the highest-ranked contact (or ``None`` if none are usable).

    Selection prefers the deterministic ``ContactRankingService`` output
    (``ranking_score``) when present, falling back to the legacy role-priority +
    confidence + primary ordering when a contact has not been ranked yet.
    Contacts flagged ``do_not_contact`` or with no e-mail are excluded.
    """
    if not contacts:
        return None

    candidates = []
    for c in contacts:
        if getattr(c, "do_not_contact", False):
            continue
        email = _contact_email(c)
        if not email:
            continue
        conf = contact_confidence(c, verify=verify)
        candidates.append((c, conf))

    if not candidates:
        return None

    candidates.sort(key=_ranking_sort_key)
    return candidates[0][0]


def rank_contacts(
    contacts: List,
    *,
    verify: Optional[Callable[[str], VerificationResult]] = None,
) -> List:
    """Return all usable contacts sorted best-first (for debugging / display)."""
    usable = [
        (c, contact_confidence(c, verify=verify))
        for c in contacts
        if not getattr(c, "do_not_contact", False) and _contact_email(c)
    ]
    usable.sort(key=_ranking_sort_key)
    return [c for c, _ in usable]
