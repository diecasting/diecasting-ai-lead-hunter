"""Outreach package — AI-powered B2B sales email generation.

Modules:
- email_generator: produce personalised sales emails from lead intelligence.
- contact_role_detector: recommend the best contact role per industry/company type.
- templates/: Markdown templates for 8 die casting / CNC / tooling industries.
"""
from app.outreach.contact_role_detector import detect_primary_role, detect_roles
from app.outreach.email_generator import generate_email, generate_email_from_lead

__all__ = [
    "generate_email",
    "generate_email_from_lead",
    "detect_roles",
    "detect_primary_role",
]
