"""Tests for contact_role_detector — industry-specific role recommendations."""
import pytest

from app.outreach.contact_role_detector import detect_primary_role, detect_roles


class TestDetectRoles:
    """Full role list detection."""

    def test_automotive_roles(self):
        roles = detect_roles(industry="automotive")
        assert "Purchasing Manager" in roles
        assert "Supplier Development Engineer" in roles
        assert "Global Sourcing Manager" in roles

    def test_ev_roles(self):
        roles = detect_roles(industry="electric vehicle")
        assert "Strategic Sourcing Manager" in roles
        assert "Supply Chain Director" in roles
        assert "Component Engineering Manager" in roles

    def test_hydraulic_roles(self):
        roles = detect_roles(industry="hydraulic")
        assert "Engineering Manager" in roles
        assert "OEM Procurement" in roles
        assert "Purchasing Manager" in roles

    def test_pump_roles(self):
        roles = detect_roles(industry="pump")
        assert "Purchasing Manager" in roles
        assert "OEM Procurement" in roles

    def test_gearbox_roles(self):
        roles = detect_roles(industry="gearbox")
        assert "Purchasing Manager" in roles
        assert "Engineering Manager" in roles

    def test_industrial_roles(self):
        roles = detect_roles(industry="industrial equipment")
        assert "Engineering Manager" in roles
        assert "OEM Procurement" in roles

    def test_aerospace_roles(self):
        roles = detect_roles(industry="aerospace")
        assert "Supply Chain Manager" in roles
        assert "Quality Assurance Manager" in roles

    def test_cnc_roles(self):
        roles = detect_roles(industry="cnc machining")
        assert "Production Manager" in roles
        assert "Purchasing Manager" in roles

    def test_tooling_roles(self):
        roles = detect_roles(industry="tooling")
        assert "Tooling Manager" in roles
        assert "Engineering Manager" in roles

    def test_mold_roles(self):
        roles = detect_roles(industry="mold")
        assert "Tooling Manager" in roles
        assert "Engineering Manager" in roles

    def test_robotics_roles(self):
        roles = detect_roles(industry="robotics")
        assert "Engineering Manager" in roles
        assert "R&D Director" in roles

    def test_max_roles_limit(self):
        roles = detect_roles(industry="automotive", max_roles=2)
        assert len(roles) == 2

    def test_no_duplicates(self):
        roles = detect_roles(industry="automotive", max_roles=5)
        assert len(roles) == len(set(r.lower() for r in roles))

    def test_unknown_industry_fallback(self):
        roles = detect_roles(industry="unknown sector")
        assert len(roles) >= 1
        assert "Purchasing Manager" in roles


class TestDetectPrimaryRole:
    """Single best-role detection."""

    def test_automotive_primary(self):
        role = detect_primary_role(industry="automotive")
        assert role == "Purchasing Manager"

    def test_ev_primary(self):
        role = detect_primary_role(industry="ev")
        assert role == "Strategic Sourcing Manager"

    def test_pump_primary(self):
        role = detect_primary_role(industry="pump")
        assert role == "Purchasing Manager"

    def test_cnc_primary(self):
        role = detect_primary_role(industry="cnc")
        assert role == "Production Manager"

    def test_tooling_primary(self):
        role = detect_primary_role(industry="tooling")
        assert role == "Tooling Manager"

    def test_unknown_primary(self):
        role = detect_primary_role(industry="random business")
        assert role in ("Purchasing Manager", "Engineering Manager", "General Manager")


class TestBusinessTypeRoles:
    """Business-type specific role overrides."""

    def test_manufacturer_oem(self):
        roles = detect_roles(industry="cnc", business_type="Manufacturer / OEM", max_roles=5)
        assert any("Supplier Development Engineer" in r for r in roles)

    def test_trader(self):
        roles = detect_roles(industry="tooling", business_type="Trader / Distributor", max_roles=5)
        assert any("Sales Director" in r for r in roles)


class TestBuyingSignalBoost:
    """Buying signal priority role boost."""

    def test_high_signal_roles(self):
        roles = detect_roles(
            industry="unknown sector", buying_signal="HIGH", max_roles=5
        )
        assert any("Strategic Sourcing Manager" in r for r in roles)

    def test_medium_signal_roles(self):
        roles = detect_roles(
            industry="unknown sector", buying_signal="MEDIUM", max_roles=5
        )
        assert any("Purchasing Manager" in r for r in roles)

    def test_low_signal_roles(self):
        roles = detect_roles(
            industry="unknown sector", buying_signal="LOW", max_roles=5
        )
        assert any("Sales Manager" in r for r in roles)


class TestEmptyInput:
    """Graceful handling of empty inputs."""

    def test_empty_industry(self):
        roles = detect_roles(industry="", max_roles=3)
        assert len(roles) > 0

    def test_empty_all(self):
        roles = detect_roles(industry="", business_type="", buying_signal="")
        assert len(roles) > 0
