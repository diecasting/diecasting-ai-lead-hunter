"""Pydantic schemas for CompanyLead (request/response validation)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CompanyLeadBase(BaseModel):
    name: str
    website: Optional[str] = None
    domain: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    employee_count: Optional[int] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    source: Optional[str] = None


class CompanyLeadCreate(CompanyLeadBase):
    """Payload for creating a lead."""


class CompanyLeadUpdate(BaseModel):
    """Payload for partially updating a lead (all fields optional)."""

    name: Optional[str] = None
    website: Optional[str] = None
    domain: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    employee_count: Optional[int] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    source: Optional[str] = None


class CompanyLeadRead(CompanyLeadBase):
    """Response schema, mapped from the ORM model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ai_score: Optional[float] = None
    ai_relevant: Optional[bool] = None
    ai_summary: Optional[str] = None
    ai_signals: Optional[str] = None
    ai_analyzed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
