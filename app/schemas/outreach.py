"""Pydantic schemas for outreach messages."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class OutreachMessageRead(BaseModel):
    """Response schema for a generated sales email."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    subject: str
    body: str
    contact_role: Optional[str] = None
    status: str = "draft"
    sent_time: Optional[datetime] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    is_followup: bool = False
    followup_seq: int = 0
    tracking_token: Optional[str] = None
    open_count: int = 0
    click_count: int = 0
    html_body: Optional[str] = None
    quality_score: Optional[int] = None
    quality_gate_status: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    send_status: str = "draft"
    sent_at: Optional[datetime] = None
    created_at: datetime


class GenerateEmailRequest(BaseModel):
    """Optional overrides for email generation."""

    industry: Optional[str] = None
    language: str = "en"
    tone: str = "professional"  # professional | friendly | direct


class ReviewGateRequest(BaseModel):
    """Reviewer override of a draft's quality gate status."""

    gate_status: str

    @field_validator("gate_status")
    @classmethod
    def _valid_gate(cls, v: str) -> str:
        if v not in ("ready", "review", "blocked"):
            raise ValueError("gate_status must be one of: ready, review, blocked")
        return v


class SendDraftResponse(BaseModel):
    """Result of a send attempt on an outreach draft."""

    success: bool
    message_id: int
    sent_at: Optional[datetime] = None
    send_status: str = "draft"
    error: Optional[str] = None
