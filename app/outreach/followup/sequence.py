"""FollowUpSequence management + step validation (Phase 6 Stage 1).

A sequence is a named list of follow-up steps ``[{"delay_days": 3,
"template": "technical_followup"}, ...]`` rendered by
:mod:`app.outreach.followup.generator` at the scheduled time.
"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.followup import FollowUpSequence

# Built-in cadence used when no sequence is configured (matches the Phase 6
# Stage 1 example: 3-day technical follow-up, then 7-day RFQ follow-up).
DEFAULT_STEPS: List[Dict[str, Any]] = [
    {"delay_days": 3, "template": "technical_followup"},
    {"delay_days": 7, "template": "rfq_followup"},
]

VALID_TEMPLATES = ("technical_followup", "rfq_followup", "value_prop_followup")


def validate_steps(steps: Any) -> List[Dict[str, Any]]:
    """Validate a steps payload; raise :class:`ValueError` with a clear reason."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    out: List[Dict[str, Any]] = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"step {i} must be an object")
        delay = step.get("delay_days")
        if not isinstance(delay, int) or delay < 1:
            raise ValueError(f"step {i}: delay_days must be an integer >= 1")
        template = (step.get("template") or "").strip()
        if not template:
            raise ValueError(f"step {i}: template is required")
        if template not in VALID_TEMPLATES:
            raise ValueError(
                f"step {i}: unknown template {template!r} "
                f"(allowed: {', '.join(VALID_TEMPLATES)})"
            )
        out.append({"delay_days": int(delay), "template": template})
    return out


def create_sequence(
    db: Session, *, name: str, steps: List[Dict[str, Any]], enabled: bool = True
) -> FollowUpSequence:
    """Create a follow-up sequence (steps are validated)."""
    validated = validate_steps(steps)
    seq = FollowUpSequence(
        name=(name or "").strip()[:120],
        steps=json.dumps(validated, ensure_ascii=False),
        enabled=enabled,
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)
    return seq


def get_sequence(db: Session, sequence_id: int) -> Optional[FollowUpSequence]:
    return db.query(FollowUpSequence).filter(FollowUpSequence.id == sequence_id).first()


def list_sequences(db: Session) -> List[FollowUpSequence]:
    return db.query(FollowUpSequence).order_by(FollowUpSequence.id.desc()).all()


def default_sequence(db: Session) -> Optional[FollowUpSequence]:
    """The first enabled sequence (used for auto-scheduling after a send)."""
    return (
        db.query(FollowUpSequence)
        .filter(FollowUpSequence.enabled.is_(True))
        .order_by(FollowUpSequence.id)
        .first()
    )


def update_sequence(
    db: Session, seq: FollowUpSequence, **fields
) -> FollowUpSequence:
    for field, value in fields.items():
        if field == "steps":
            value = json.dumps(validate_steps(value), ensure_ascii=False)
        if value is not None:
            setattr(seq, field, value)
    db.add(seq)
    db.commit()
    db.refresh(seq)
    return seq


def delete_sequence(db: Session, seq: FollowUpSequence) -> None:
    db.delete(seq)
    db.commit()
