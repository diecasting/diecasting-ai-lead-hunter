"""Tests for the email sender module (SMTP delivery + tracking)."""
import pytest

from app.crud import outreach as outreach_crud
from app.crud import outreach_events as events_crud
from app.outreach.sender import _smtp_configured, send_email, send_message_by_id


class _FakeSmtpTransport:
    """In-memory stand-in for an ``smtplib.SMTP`` connection (IO boundary mock)."""

    def __init__(self):
        self.starttls_called = False
        self.login_called = False
        self.sent = []

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_called = True

    def send_message(self, msg):
        self.sent.append(msg)


class TestSmtpTransportInjection:
    """Full mock-replaceability of the SMTP IO boundary (Stage 0, IO audit)."""

    def test_transport_injection_sends_without_real_smtp(self, client, db, monkeypatch):
        """When SMTP is configured but a transport is injected, the real
        network connection is bypassed and the injected transport is used."""
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "user@example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "secret")

        resp = client.post(
            "/leads",
            json={
                "name": "TransportInj Co",
                "website": "https://transportinj.example.com",
                "contact_email": "buyer@transportinj.com",
            },
        )
        lead_id = resp.json()["id"]
        client.post(f"/leads/{lead_id}/generate-email")
        message = outreach_crud.get_by_lead(db, lead_id)[0]

        transport = _FakeSmtpTransport()
        # dry_run must be False so the real-delivery path executes (using transport)
        receipt = send_email(
            db, message, "buyer@transportinj.com", dry_run=False, transport=transport
        )
        assert receipt["success"] is True
        assert receipt["dry_run"] is False
        assert len(transport.sent) == 1
        assert transport.login_called is True
        assert transport.sent[0]["To"] == "buyer@transportinj.com"

    def test_dry_run_still_records_even_with_transport(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "DryRunTransport Co",
                "website": "https://dryruntransport.example.com",
                "contact_email": "buyer@dryruntransport.com",
            },
        )
        lead_id = resp.json()["id"]
        client.post(f"/leads/{lead_id}/generate-email")
        message = outreach_crud.get_by_lead(db, lead_id)[0]

        transport = _FakeSmtpTransport()
        receipt = send_email(
            db, message, "buyer@dryruntransport.com", dry_run=True, transport=transport
        )
        assert receipt["dry_run"] is True
        # In dry-run the transport is never used.
        assert len(transport.sent) == 0


class TestSmtpConfig:
    """SMTP configuration detection."""

    def test_no_config_dry_run(self, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "")
        assert _smtp_configured() is False

    def test_with_config(self, monkeypatch):
        from app import config as config_mod

        monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_user", "user@example.com")
        monkeypatch.setattr(config_mod.settings, "smtp_password", "secret")
        assert _smtp_configured() is True


class TestSendEmailDryRun:
    """Dry-run mode (no real SMTP)."""

    def test_dry_run_records_send(self, client, db):
        # Create a lead with email
        resp = client.post(
            "/leads",
            json={
                "name": "SenderTest Co",
                "website": "https://sendertest.example.com",
                "industry": "automotive",
                "description": "parts",
                "contact_email": "buyer@sendertest.com",
            },
        )
        lead_id = resp.json()["id"]

        # Generate email
        resp = client.post(f"/leads/{lead_id}/generate-email")
        assert resp.status_code == 201
        msg = resp.json()
        message_id = msg["id"]

        # Send in dry-run mode
        from app.crud import outreach as oc

        message = oc.get(db, message_id)
        receipt = send_email(db, message, "buyer@sendertest.com", dry_run=True)
        assert receipt["success"] is True
        assert receipt["dry_run"] is True
        assert receipt["recipient"] == "buyer@sendertest.com"
        assert receipt["message_id"] == message_id

        # Verify DB state: message marked sent, event recorded
        resp = client.get(f"/outreach/leads/{lead_id}/messages")
        messages = resp.json()
        assert len(messages) >= 1
        sent_msg = [m for m in messages if m["status"] == "sent"]
        assert len(sent_msg) == 1
        assert sent_msg[0]["sent_time"] is not None
        assert sent_msg[0]["recipient"] == "buyer@sendertest.com"

    def test_send_by_id(self, client, db):
        resp = client.post(
            "/leads",
            json={
                "name": "SendById Co",
                "website": "https://sendbyid.example.com",
                "industry": "ev",
                "contact_email": "purchasing@sendbyid.com",
            },
        )
        lead_id = resp.json()["id"]
        client.post(f"/leads/{lead_id}/generate-email")

        msgs = outreach_crud.get_by_lead(db, lead_id)
        message_id = msgs[0].id
        receipt = send_message_by_id(
            db, message_id, "purchasing@sendbyid.com", dry_run=True
        )
        assert receipt["success"] is True
        assert receipt["message_id"] == message_id

    def test_send_unknown_message(self, client, db):
        receipt = send_message_by_id(db, 999999, "x@y.com", dry_run=True)
        assert receipt["success"] is False
        assert "not found" in receipt["error"]
