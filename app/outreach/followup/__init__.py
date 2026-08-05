"""Follow-up Automation Engine (Phase 6 Stage 1).

Package layout:

* ``legacy``    — the original fixed-cadence follow-up module (kept for
                  backward compatibility; see ``schedule_followups``).
* ``sequence``  — :class:`FollowUpSequence` CRUD + step validation + default
                  sequence steps.
* ``generator`` — renders a follow-up email (draft ``OutreachMessage``) from
                  a sequence step's template.
* ``scheduler`` — after an initial email is sent, creates the follow-up
                  schedule (:class:`OutreachFollowUp` rows) and processes due
                  follow-ups (lead-status guard → generate → send).
"""
from app.outreach.followup.legacy import (
    FOLLOWUP_SCHEDULE,
    get_due_followups,
    schedule_followups,
)

__all__ = [
    "FOLLOWUP_SCHEDULE",
    "get_due_followups",
    "schedule_followups",
]
