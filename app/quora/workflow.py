"""Phase 7 content workflow — explicit status state machines.

Two small, auditable transition maps (no external dependency): one for Quora
questions, one for answers. ``validate_*_transition`` returns the target when
allowed and raises ``ValueError`` otherwise, so the API layer can convert that
into a 400.
"""
from app.models.quora import (
    ANSWER_DRAFT,
    ANSWER_EXPORTED,
    ANSWER_PUBLISHED,
    ANSWER_REVIEW,
    QUESTION_ANSWERED,
    QUESTION_DRAFTED,
    QUESTION_NEW,
    QUESTION_PUBLISHED,
    QUESTION_RESEARCHED,
)

# question: current -> allowed next
QUESTION_TRANSITIONS = {
    QUESTION_NEW: [
        QUESTION_RESEARCHED,
        QUESTION_DRAFTED,
        QUESTION_ANSWERED,
        QUESTION_PUBLISHED,
    ],
    QUESTION_RESEARCHED: [
        QUESTION_NEW,
        QUESTION_DRAFTED,
        QUESTION_ANSWERED,
        QUESTION_PUBLISHED,
    ],
    QUESTION_DRAFTED: [
        QUESTION_NEW,
        QUESTION_RESEARCHED,
        QUESTION_ANSWERED,
        QUESTION_PUBLISHED,
    ],
    QUESTION_ANSWERED: [QUESTION_NEW, QUESTION_DRAFTED, QUESTION_PUBLISHED],
    QUESTION_PUBLISHED: [QUESTION_NEW, QUESTION_ANSWERED],
}

# answer: current -> allowed next
ANSWER_TRANSITIONS = {
    ANSWER_DRAFT: [ANSWER_REVIEW, ANSWER_PUBLISHED, ANSWER_EXPORTED],
    ANSWER_REVIEW: [ANSWER_DRAFT, ANSWER_PUBLISHED, ANSWER_EXPORTED],
    ANSWER_PUBLISHED: [ANSWER_DRAFT, ANSWER_EXPORTED],
    ANSWER_EXPORTED: [ANSWER_DRAFT, ANSWER_PUBLISHED],
}


def validate_question_transition(current: str, target: str) -> str:
    """Return ``target`` if the question transition is allowed, else raise."""
    current = (current or QUESTION_NEW).strip().lower()
    target = (target or "").strip().lower()
    allowed = QUESTION_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Invalid question status transition: {current} -> {target}. "
            f"Allowed: {allowed}"
        )
    return target


def validate_answer_transition(current: str, target: str) -> str:
    """Return ``target`` if the answer transition is allowed, else raise."""
    current = (current or ANSWER_DRAFT).strip().lower()
    target = (target or "").strip().lower()
    allowed = ANSWER_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Invalid answer status transition: {current} -> {target}. "
            f"Allowed: {allowed}"
        )
    return target
