"""Tests for the outreach quality gate wired into the send path (Phase 4 Stage 0).

Verifies that ``send_email`` refuses to deliver when the quality gate blocks an
address (invalid / risky / do_not_contact), and still delivers normally when the
gate passes or is absent (regression: no behavioural change without a gate).
"""
import pytest

from app.crud import contacts as contacts_crud
from app.crud import outreach as outreach_crud
from app.outreach.quality_gate import EmailQualityGate
from app.outreach.sender import send_email
from app.outreach.verifiers import SyntaxEmailVerifier


class _FakeSmtpTransport:
    def __init__(self):
        self.sent = []
        self.login_called = False

    def starttls(self):
        pass

    def login(self, user, password):
        self.login_called = True

    def send_message(self, msg):
        self.sent.append(msg)


def _make_lead_with_email(client, email="buyer@acme.com", **extra):
    payload = {
        "name": "GateSend Co",
        "website": "https://gatesend.example.com",
        "contact_email": email,
    }
    payload.update(extra)
    resp = client.post("/leads", json=payload)
    return resp.json()["id"]


def _make_message(client, db, lead_id):
    client.post(f"/leads/{lead_id}/generate-email")
    return outreach_crud.get_by_lead(db, lead_id)[0]


class TestSendGateBlocks:
    def test_invalid_email_blocked(self, client, db, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "not-an-email")
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate()

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "not-an-email", dry_run=False, transport=transport, gate=gate
        )
        assert receipt["success"] is False
        assert receipt["blocked"] is True
        assert len(transport.sent) == 0  # nothing delivered

    def test_disposable_email_allowed_stage1(self, client, db, monkeypatch):
        """Stage 1: risky (disposable) is a soft signal, not a hard block."""
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "spam@mailinator.com")
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate()  # block_risky defaults to False

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "spam@mailinator.com", dry_run=False, transport=transport, gate=gate
        )
        assert receipt.get("blocked") is not True  # not blocked
        assert receipt["success"] is True
        assert len(transport.sent) == 1

    def test_disposable_blocked_when_block_risky_set(self, client, db, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "spam@mailinator.com")
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate(block_risky=True)

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "spam@mailinator.com", dry_run=False, transport=transport, gate=gate
        )
        assert receipt["blocked"] is True
        assert len(transport.sent) == 0

    def test_do_not_contact_lead_blocked(self, client, db, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "buyer@acme.com", do_not_contact=True)
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate()

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "buyer@acme.com", dry_run=False, transport=transport, gate=gate,
            lead=db.query(__import__("app.models.lead", fromlist=["CompanyLead"]).CompanyLead).filter_by(id=lead_id).first(),
        )
        assert receipt["blocked"] is True
        assert len(transport.sent) == 0

    def test_force_override_delivers(self, client, db, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "spam@mailinator.com")
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate()

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "spam@mailinator.com", dry_run=False, transport=transport,
            gate=gate, force=True,
        )
        assert receipt["success"] is True
        assert receipt.get("blocked") is not True
        assert len(transport.sent) == 1


class TestSendGateAllows:
    def test_valid_email_delivers(self, client, db, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "buyer@acme.com")
        message = _make_message(client, db, lead_id)
        gate = EmailQualityGate()

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "buyer@acme.com", dry_run=False, transport=transport, gate=gate
        )
        assert receipt["success"] is True
        assert receipt.get("blocked") is None
        assert len(transport.sent) == 1

    def test_no_gate_regression_still_sends(self, client, db, monkeypatch):
        """Regression: when no gate is supplied, behaviour is unchanged."""
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "u@e.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "pw")

        lead_id = _make_lead_with_email(client, "spam@mailinator.com")
        message = _make_message(client, db, lead_id)

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "spam@mailinator.com", dry_run=False, transport=transport
        )
        # No gate -> legacy behaviour (delivers regardless of quality).
        assert receipt["success"] is True
        assert len(transport.sent) == 1
