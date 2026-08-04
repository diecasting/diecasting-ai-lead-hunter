"""Tests for AI email generator — deterministic and API integration."""
import pytest

from app.outreach.email_generator import (
    generate_email,
    generate_email_from_lead,
)


class TestGenerateEmailDeterministic:
    """Deterministic email generation (no OpenAI required)."""

    def test_automotive_email(self):
        intelligence = {
            "company": "AutoParts GmbH",
            "industry": "automotive",
            "products": "engine blocks, transmission housings",
            "materials": "aluminum, magnesium",
            "manufacturing_process": "die casting, CNC machining",
            "buying_signal": "HIGH",
            "reason": "Automotive OEM seeking new die casting suppliers",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert result["subject"]
        assert result["body"]
        assert result["opening"]
        assert result["call_to_action"]
        assert "AutoParts GmbH" in result["opening"]
        assert result["contact_role"]

    def test_ev_email(self):
        intelligence = {
            "company": "VoltDrive Inc",
            "industry": "electric vehicle",
            "products": "battery housings",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "MEDIUM",
            "reason": "EV startup expanding production",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "VoltDrive" in result["opening"]
        assert result["subject"]
        assert result["body"]

    def test_hydraulic_email(self):
        intelligence = {
            "company": "HydroSystems Ltd",
            "industry": "hydraulic",
            "products": "valve bodies",
            "materials": "aluminum A380",
            "manufacturing_process": "die casting, CNC",
            "buying_signal": "HIGH",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "HydroSystems" in result["opening"]

    def test_pump_email(self):
        intelligence = {
            "company": "FlowPump Co",
            "industry": "pump",
            "products": "centrifugal pump housings",
            "materials": "aluminum, cast iron",
            "manufacturing_process": "sand casting, machining",
            "buying_signal": "MEDIUM",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "FlowPump" in result["opening"]

    def test_gearbox_email(self):
        intelligence = {
            "company": "GearTech Ltd",
            "industry": "gearbox",
            "products": "transmission housings",
            "materials": "aluminum ADC12",
            "manufacturing_process": "die casting",
            "buying_signal": "HIGH",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "GearTech" in result["opening"]

    def test_industrial_equipment_email(self):
        intelligence = {
            "company": "IndMach Corp",
            "industry": "industrial equipment",
            "products": "machine frames, enclosures",
            "materials": "aluminum, steel",
            "manufacturing_process": "die casting, welding",
            "buying_signal": "MEDIUM",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "IndMach" in result["opening"]

    def test_cnc_email(self):
        intelligence = {
            "company": "PrecisionCNC Inc",
            "industry": "cnc machining",
            "products": "custom machined parts",
            "materials": "aluminum 6061, 7075",
            "manufacturing_process": "5 axis CNC machining",
            "buying_signal": "MEDIUM",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "PrecisionCNC" in result["opening"]

    def test_tooling_email(self):
        intelligence = {
            "company": "MoldWorks GmbH",
            "industry": "tooling",
            "products": "injection molds, die casting dies",
            "materials": "H13 tool steel",
            "manufacturing_process": "CNC EDM, wire EDM",
            "buying_signal": "LOW",
            "reason": "",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "MoldWorks" in result["opening"]

    def test_empty_company_uses_placeholder(self):
        intelligence = {
            "company": "",
            "industry": "automotive",
            "products": "",
            "materials": "",
            "manufacturing_process": "",
            "buying_signal": "",
            "reason": "",
            "business_type": "",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "your company" in result["opening"]
        assert result["subject"]
        assert result["body"]

    def test_unknown_industry_fallback(self):
        intelligence = {
            "company": "RandomBiz",
            "industry": "some unknown sector",
            "products": "",
            "materials": "",
            "manufacturing_process": "",
            "buying_signal": "",
            "reason": "",
            "business_type": "",
        }
        result = generate_email(intelligence, use_llm=False)
        assert "RandomBiz" in result["opening"]
        assert result["subject"]

    def test_result_keys_complete(self):
        intelligence = {
            "company": "TestCorp",
            "industry": "automotive",
            "products": "parts",
            "materials": "aluminum",
            "manufacturing_process": "die casting",
            "buying_signal": "HIGH",
            "reason": "good fit",
            "business_type": "Manufacturer / OEM",
        }
        result = generate_email(intelligence, use_llm=False)
        for key in ("subject", "opening", "body", "call_to_action", "contact_role"):
            assert key in result
            assert result[key]

    def test_trader_business_type_role(self):
        intelligence = {
            "company": "TradeHouse",
            "industry": "automotive",
            "products": "components",
            "materials": "",
            "manufacturing_process": "",
            "buying_signal": "LOW",
            "reason": "",
            "business_type": "Trader / Distributor",
        }
        result = generate_email(intelligence, use_llm=False)
        assert result["contact_role"]


class TestGenerateEmailFromLead:
    """Email generation from a CompanyLead ORM object (via API integration)."""

    def test_generate_from_lead(self, client):
        """Create a lead, then call the generate-email endpoint."""
        # Create a lead with some intelligence data
        resp = client.post(
            "/leads",
            json={
                "name": "AutoSupplier GmbH",
                "website": "https://autosupplier.example.com",
                "industry": "automotive",
                "description": "engine blocks and transmission parts",
                "country": "Germany",
            },
        )
        assert resp.status_code == 201
        lead = resp.json()
        lead_id = lead["id"]

        # Generate email
        resp = client.post(f"/leads/{lead_id}/generate-email")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["lead_id"] == lead_id
        assert data["subject"]
        assert data["body"]
        assert data["status"] == "draft"
        assert "AutoSupplier" in data["body"]

    def test_generate_email_nonexistent_lead(self, client):
        resp = client.post("/leads/99999/generate-email")
        assert resp.status_code == 404

    def test_list_drafts(self, client):
        """Create a lead, generate email, then list drafts."""
        resp = client.post(
            "/leads",
            json={
                "name": "DraftTest Co",
                "website": "https://drafttest.example.com",
                "industry": "cnc machining",
                "description": "custom machined parts",
            },
        )
        assert resp.status_code == 201
        lead_id = resp.json()["id"]

        # Generate an email → creates a draft
        resp = client.post(f"/leads/{lead_id}/generate-email")
        assert resp.status_code == 201

        # List drafts
        resp = client.get("/outreach/drafts")
        assert resp.status_code == 200
        drafts = resp.json()
        assert len(drafts) >= 1
        assert drafts[0]["status"] == "draft"

    def test_get_lead_messages(self, client):
        """Get all outreach messages for a specific lead."""
        resp = client.post(
            "/leads",
            json={
                "name": "MsgTest Inc",
                "website": "https://msgtest.example.com",
                "industry": "tooling",
                "description": "die casting dies",
            },
        )
        lead_id = resp.json()["id"]

        # Generate an email
        client.post(f"/leads/{lead_id}/generate-email")

        # Get messages for that lead
        resp = client.get(f"/outreach/leads/{lead_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) >= 1
        assert messages[0]["lead_id"] == lead_id

    def test_get_lead_messages_nonexistent_lead(self, client):
        resp = client.get("/outreach/leads/99999/messages")
        assert resp.status_code == 404
