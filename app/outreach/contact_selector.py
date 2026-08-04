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


def select_best_contact(
    contacts: List,
    *,
    verify: Optional[Callable[[str], VerificationResult]] = None,
    preferred_roles: Optional[List[str]] = None,
) -> Optional[object]:
    """Return the highest-ranked contact (or ``None`` if none are usable).

    Ranking key (descending): role priority points, then confidence, then
    primary flag, then has-email. Contacts flagged ``do_not_contact`` or with no
    e-mail are excluded.
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

    # Sort by: role priority (asc), confidence (desc), primary (desc).
    def sort_key(item):
        c, conf = item
        return (
            role_priority(_contact_role(c)),
            -conf,
            -int(bool(getattr(c, "is_primary", False))),
        )

    candidates.sort(key=sort_key)
    return candidates[0][0]


def rank_contacts(
    contacts: List,
    *,
    verify: Optional[Callable[[str], VerificationResult]] = None,
) -> List:
    """Return all usable contacts sorted best-first (for debugging / display)."""
    usable = [c for c in contacts if not getattr(c, "do_not_contact", False) and _contact_email(c)]
    usable.sort(key=lambda c: (
        role_priority(_contact_role(c)),
        -contact_confidence(c, verify=verify),
        -int(bool(getattr(c, "is_primary", False))),
    ))
    return usable
