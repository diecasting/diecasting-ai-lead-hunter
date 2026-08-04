"""Pydantic schemas for the Phase 3 Stage 1 CRM tables.

Covers: contacts, lead_sources, email_verifications, email_tracking,
reply_inbox, unsubscribes.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
class ContactBase(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    title: Optional[str] = None
    is_primary: bool = False
    do_not_contact: bool = False


class ContactCreate(ContactBase):
    lead_id: int


class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    title: Optional[str] = None
    is_primary: Optional[bool] = None
    do_not_contact: Optional[bool] = None


class ContactRead(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Lead sources
# ---------------------------------------------------------------------------
class LeadSourceBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class LeadSourceCreate(LeadSourceBase):
    pass


class LeadSourceUpdate(BaseModel):
    description: Optional[str] = None
    is_active: Optional[bool] = None


class LeadSourceRead(LeadSourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Email verifications
# ---------------------------------------------------------------------------
class EmailVerificationCreate(BaseModel):
    email: str
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    status: str = "unknown"
    is_deliverable: Optional[str] = None
    reason: Optional[str] = None


class EmailVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    email: str
    status: str
    is_deliverable: Optional[str] = None
    reason: Optional[str] = None
    checked_at: datetime


# ---------------------------------------------------------------------------
# Email tracking
# ---------------------------------------------------------------------------
class EmailTrackingCreate(BaseModel):
    message_id: int
    contact_id: Optional[int] = None
    event_type: str  # open | click
    tracking_token: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None


class EmailTrackingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    contact_id: Optional[int] = None
    event_type: str
    tracking_token: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Reply inbox
# ---------------------------------------------------------------------------
class ReplyInboxCreate(BaseModel):
    message_id: Optional[int] = None
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    from_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    is_bounce: bool = False


class ReplyInboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: Optional[int] = None
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    from_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    is_bounce: bool
    received_at: datetime


# ---------------------------------------------------------------------------
# Unsubscribes
# ---------------------------------------------------------------------------
class UnsubscribeCreate(BaseModel):
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    email: Optional[str] = None
    reason: Optional[str] = None
    token: Optional[str] = None


class UnsubscribeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    email: Optional[str] = None
    reason: Optional[str] = None
    token: Optional[str] = None
    created_at: datetime
