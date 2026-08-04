"""Outreach package — AI-powered B2B sales email generation & automation.

Modules:
- email_generator: produce personalised sales emails from lead intelligence.
- contact_role_detector: recommend the best contact role per industry/company type.
- workflow: lead lifecycle state machine + daily automation pipeline.
- sender: SMTP-based email delivery with send tracking.
- followup: follow-up cadence (Day 0/5/12/30) generation.
- templates/: Markdown templates for 8 die casting / CNC / tooling industries.
"""
from app.outreach.contact_role_detector import detect_primary_role, detect_roles
from app.outreach.email_generator import generate_email, generate_email_from_lead
from app.outreach.followup import get_due_followups, schedule_followups
from app.outreach.sender import send_email, send_message_by_id
from app.outreach.workflow import (
    VALID_TRANSITIONS,
    approve_and_send,
    can_transition,
    generate_email_for_lead,
    run_daily_pipeline,
    run_pipeline_for_lead,
    transition,
)

__all__ = [
    "generate_email",
    "generate_email_from_lead",
    "detect_roles",
    "detect_primary_role",
    "workflow",
    "approve_and_send",
    "can_transition",
    "generate_email_for_lead",
    "run_daily_pipeline",
    "run_pipeline_for_lead",
    "transition",
    "VALID_TRANSITIONS",
    "send_email",
    "send_message_by_id",
    "schedule_followups",
    "get_due_followups",
]
