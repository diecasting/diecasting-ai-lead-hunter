"""Email verification framework (Phase 4 Stage 0).

Defines the ``BaseEmailVerifier`` interface plus a small ``VerificationResult``
value object used by all verifiers, and the *verdict* vocabulary shared across
the outreach quality gate.

Verdicts
--------
A verifier reports one of four verdicts:

    VALID    — address looks deliverable / acceptable to send to.
    INVALID  — address is structurally or provably undeliverable (hard block).
    RISKY    — address is deliverable-looking but undesirable (disposable,
               role account, no MX, etc.) — send should be blocked by the gate
               unless explicitly overridden.
    UNKNOWN  — insufficient evidence to decide (treated like VALID by the gate,
               but recorded so a later check can upgrade it).

The ``EmailQualityGate`` (see ``app.outreach/quality_gate.py``) blocks
``INVALID`` / ``RISKY`` and also honors ``do_not_contact`` on the related lead
or contact before any real send happens.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Verdict vocabulary (kept as module-level constants so they stay in sync with
# the ``email_verifications.status`` column enum values).
VALID = "valid"
INVALID = "invalid"
RISKY = "risky"
UNKNOWN = "unknown"

# Statuses the outreach quality gate will *hard*-block on.
# As of Phase 4 Stage 1, RISKY is a SOFT signal (it lowers recipient confidence
# but does not by itself prevent delivery) — only INVALID is a hard block. The
# stricter "block risky" posture can be re-enabled via EmailQualityGate(
# block_risky=True). do_not_contact is enforced separately by the gate.
BLOCKED_STATUSES = {INVALID}

# Default per-verdict deliverability hint used when a verifier does not set it
# explicitly. ``yes`` / ``no`` / ``unknown`` mirror the DB ``is_deliverable``
# column semantics.
_DELIVERABILITY_BY_VERDICT = {
    VALID: "yes",
    INVALID: "no",
    RISKY: "unknown",
    UNKNOWN: "unknown",
}


@dataclass
class VerificationResult:
    """Outcome of a single verification check (or a composite of several)."""

    status: str = UNKNOWN            # one of VALID / INVALID / RISKY / UNKNOWN
    verifier: str = "base"           # name of the verifier that produced it
    is_deliverable: Optional[str] = None  # yes | no | unknown
    reason: str = ""                 # human-readable explanation
    # Optional 0-100 confidence/quality score (higher = safer to send).
    score: Optional[int] = None
    # Optional nested detail (e.g. per-check results) for explainability.
    detail: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.is_deliverable is None:
            self.is_deliverable = _DELIVERABILITY_BY_VERDICT.get(
                self.status, "unknown"
            )

    def is_blocked(self) -> bool:
        """True when this verdict should stop an outreach send."""
        return self.status in BLOCKED_STATUSES

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "verifier": self.verifier,
            "is_deliverable": self.is_deliverable,
            "reason": self.reason,
            "score": self.score,
            "detail": self.detail,
        }


class BaseEmailVerifier(ABC):
    """Interface every e-mail verifier must implement.

    ``verify`` is the single entry point. Implementations should be pure and
    deterministic so they are trivially unit-testable; any network / DNS access
    must go through an injectable dependency (passed in ``__init__``) so tests
    can supply a fake without touching the real network.
    """

    #: Short stable name used in ``VerificationResult.verifier`` and logs.
    name: str = "base"

    @abstractmethod
    def verify(self, email: str) -> VerificationResult:
        """Return a :class:`VerificationResult` for ``email``."""
        raise NotImplementedError

    def __call__(self, email: str) -> VerificationResult:
        return self.verify(email)
