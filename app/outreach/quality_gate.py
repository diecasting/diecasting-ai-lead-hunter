"""Outreach Quality Gate (Phase 4 Stage 0 → Stage 1).

A composite verifier that runs an address through the configured verifier chain
and aggregates the results into a single verdict, then additionally blocks sends
when the related ``CompanyLead`` or ``Contact`` is flagged ``do_not_contact``.

**Stage 1 policy change — risky != block.** Only hard ``INVALID`` verdicts (and
``do_not_contact``) stop a send. A ``RISKY`` verdict (role account, disposable,
no MX, API "accept_all", etc.) is now a *soft* signal: it lowers the recipient's
confidence score but does **not** by itself prevent delivery. The previous
"block risky" behaviour can be re-enabled with ``block_risky=True`` for
deployments that prefer the stricter posture.

The gate is injectable (``verifiers=``) so tests can run it fully offline, and
``check`` returns a :class:`VerificationResult` carrying the per-verifier
``checks`` detail for explainability / storage.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.lead import CompanyLead
from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    BaseEmailVerifier,
    VerificationResult,
)
from app.outreach.verifiers import default_verifier_chain


class EmailQualityGate(BaseEmailVerifier):
    """Composite verifier that produces a single outreach verdict."""

    name = "quality_gate"

    def __init__(
        self,
        verifiers: Optional[List[BaseEmailVerifier]] = None,
        *,
        block_risky: bool = False,
    ) -> None:
        self._verifiers: List[BaseEmailVerifier] = verifiers or default_verifier_chain()
        # Stage 1: RISKY no longer blocks by default.
        self.block_risky = block_risky

    # Order of precedence for the composite verdict. INVALID > RISKY > UNKNOWN >
    # VALID — the most conservative (worst) result wins, because a single hard
    # failure means the address must not be sent to.
    _RANK = {VALID: 0, UNKNOWN: 1, RISKY: 2, "invalid": 3}

    def check(self, email: str) -> VerificationResult:
        """Run all verifiers and aggregate into one verdict.

        Returns a :class:`VerificationResult` whose ``detail["checks"]`` holds
        each verifier's result dict, ``status`` is the conservative aggregate,
        and ``score`` is the *minimum* component score (the weakest link).
        """
        results: List[VerificationResult] = [v.verify(email) for v in self._verifiers]

        aggregate = VALID
        worst_rank = self._RANK[VALID]
        min_score = 100
        for r in results:
            rank = self._RANK.get(r.status, self._RANK[UNKNOWN])
            if rank > worst_rank:
                worst_rank = rank
                aggregate = r.status
            if r.score is not None:
                min_score = min(min_score, r.score)

        # Map the worst rank back to a verdict (INVALID is stored as "invalid").
        if worst_rank >= self._RANK["invalid"]:
            aggregate = "invalid"

        reason = "; ".join(
            f"{r.verifier}:{r.status}" for r in results if r.status != VALID
        ) or "all checks passed"

        return VerificationResult(
            status=aggregate,
            verifier=self.name,
            is_deliverable=results[0].is_deliverable if results else None,
            reason=reason,
            score=min_score if min_score != 100 or aggregate == VALID else min_score,
            detail={"checks": [r.to_dict() for r in results]},
        )

    # ``BaseEmailVerifier.verify`` alias.
    def verify(self, email: str) -> VerificationResult:
        return self.check(email)

    # ------------------------------------------------------------------
    # Pre-send decision (the actual gate used by the sender)
    # ------------------------------------------------------------------
    def allow_send(
        self,
        email: str,
        *,
        lead: Optional[CompanyLead] = None,
        contact: Optional[Contact] = None,
        db: Optional[Session] = None,
        force: bool = False,
    ) -> VerificationResult:
        """Decide whether an outreach send to ``email`` is permitted.

        Blocks when:
          * the composite verdict is INVALID (hard fail), or
          * ``block_risky`` is enabled and the verdict is RISKY, or
          * the related lead / contact has ``do_not_contact`` set.

        A plain RISKY verdict is otherwise allowed (Stage 1: risky != block) but
        the caller can consult the returned ``score`` / ``status`` to down-rank
        the recipient. ``force=True`` bypasses everything.
        """
        if force:
            return VerificationResult(
                status=VALID, verifier=self.name, reason="forced override", score=100
            )

        # do_not_contact short-circuits everything.
        dnc = False
        if lead is not None and getattr(lead, "do_not_contact", False):
            dnc = True
        if contact is not None and getattr(contact, "do_not_contact", False):
            dnc = True
        if dnc:
            return VerificationResult(
                status="invalid", verifier=self.name,
                reason="recipient is do_not_contact", score=0,
            )

        result = self.check(email)
        # Stage 1: RISKY is a soft signal. By default it is NOT blocked; the
        # caller can still see the RISKY status and down-rank the recipient.
        # When ``block_risky`` is enabled we hard-block it (reported as INVALID
        # so ``is_blocked()`` stays the single source of truth).
        if self.block_risky and result.status == RISKY:
            return VerificationResult(
                status=INVALID, verifier=self.name,
                reason=f"risky blocked by policy: {result.reason}",
                score=result.score, detail=result.detail,
            )
        return result
