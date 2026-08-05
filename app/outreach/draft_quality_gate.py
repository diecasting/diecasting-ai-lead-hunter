"""Email draft quality auto-gate (Phase 4 Stage 3).

Turns the 0-100 email ``quality_score`` (computed by
``app.outreach.email_quality.score_email_quality``) into a discrete gate
decision so drafts can be filtered / blocked in the CRM before a human
reviews or sends them:

  * ``ready``   — quality >= READY_THRESHOLD (default 70): safe to release.
  * ``review``  — BLOCK_THRESHOLD <= quality < READY_THRESHOLD: needs a human
                  look before it can be released.
  * ``blocked`` — quality < BLOCK_THRESHOLD (default 40), or recompute failed:
                  must not be auto-approved.
  * None        — no quality score available (legacy / unscored).

The module is pure and deterministic (no LLM, no IO) so it is trivially
unit-testable and can run in CI / the CRM.
"""
from dataclasses import dataclass
from typing import Optional

from app.outreach.context import CustomerContext
from app.outreach.email_quality import score_email_quality

READY_THRESHOLD = 70
BLOCK_THRESHOLD = 40

GATE_READY = "ready"
GATE_REVIEW = "review"
GATE_BLOCKED = "blocked"

VALID_GATE_STATUSES = (GATE_READY, GATE_REVIEW, GATE_BLOCKED)


@dataclass
class GateDecision:
    status: Optional[str]
    can_send: bool
    reason: str


def classify_quality_gate(
    quality_score: Optional[int],
    *,
    ready_threshold: int = READY_THRESHOLD,
    block_threshold: int = BLOCK_THRESHOLD,
) -> Optional[str]:
    """Map a 0-100 quality score to a gate status (or None if unscored)."""
    if quality_score is None:
        return None
    if quality_score >= ready_threshold:
        return GATE_READY
    if quality_score >= block_threshold:
        return GATE_REVIEW
    return GATE_BLOCKED


def gate_allows_send(status: Optional[str]) -> bool:
    """A draft may be auto-released / sent only when its gate status is ``ready``."""
    return status == GATE_READY


def evaluate_message(
    message: object,
    ctx: Optional[CustomerContext] = None,
    *,
    ready_threshold: int = READY_THRESHOLD,
    block_threshold: int = BLOCK_THRESHOLD,
) -> GateDecision:
    """Decide the gate for a stored message (duck-typed on OutreachMessage).

    Uses the stored ``quality_score`` when present; otherwise it recomputes
    the score from ``message.body`` + ``ctx`` (best-effort, e.g. for legacy
    drafts created before scoring existed). A message with no body resolves to
    ``blocked`` because it cannot be sent.
    """
    quality_score = getattr(message, "quality_score", None)
    if quality_score is None:
        body = getattr(message, "body", "") or ""
        if body:
            try:
                quality_score = score_email_quality(body, ctx).get("quality")
            except Exception:
                quality_score = None

    status = classify_quality_gate(
        quality_score, ready_threshold=ready_threshold, block_threshold=block_threshold
    )
    if quality_score is None:
        return GateDecision(
            status=None,
            can_send=False,
            reason="no quality score available; manual review required",
        )
    if status == GATE_READY:
        return GateDecision(
            status=status, can_send=True, reason=f"quality {quality_score} >= {ready_threshold}"
        )
    if status == GATE_REVIEW:
        return GateDecision(
            status=status,
            can_send=False,
            reason=f"quality {quality_score} below ready threshold {ready_threshold}",
        )
    return GateDecision(
        status=status,
        can_send=False,
        reason=f"quality {quality_score} below block threshold {block_threshold}",
    )
