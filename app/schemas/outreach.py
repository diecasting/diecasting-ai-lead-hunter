"""Pydantic schemas for outreach messages."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OutreachMessageRead(BaseModel):
    """Response schema for a generated sales email."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    subject: str
    body: str
    contact_role: Optional[str] = None
    status: str = "draft"
    created_at: datetime


class GenerateEmailRequest(BaseModel):
    """Optional overrides for email generation."""

    industry: Optional[str] = None
    language: str = "en"
    tone: str = "professional"  # professional | friendly | direct
