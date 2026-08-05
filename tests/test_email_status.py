"""Phase 6 Stage 4: production SMTP (SiteGround) configuration tests.

Covers implicit-SSL selection on port 465, STARTTLS on other ports,
authentication failure handling, the mock fallback, the
``GET /outreach/email-status`` shape (no password leak), and the
``POST /outreach/email-test`` connectivity endpoint.
"""
import json

import pytest
import smtplib

from app.outreach import sender as sender_mod
from app.outreach.sender import MockEmailSender, SmtpEmailSender, get_email_sender


def _configure_smtp(monkeypatch, *, port=465, password="secret"):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "smtp_host", "sgp14.siteground.asia")
    monkeypatch.setattr(config_mod.settings, "smtp_port", port)
    monkeypatch.setattr(config_mod.settings, "smtp_username", "sales@alumcasting.com")
    monkeypatch.setattr(config_mod.settings, "smtp_password", password)
    monkeypatch.setattr(config_mod.settings, "smtp_from_email", "sales@alumcasting.com")
    monkeypatch.setattr(config_mod.settings, "smtp_use_tls", True)


# ---------------------------------------------------------------------------
# Connection security: SMTP_SSL on 465, STARTTLS elsewhere
# ---------------------------------------------------------------------------
def test_smtp_ssl_used_on_port_465(monkeypatch):
    calls: dict = {}

    class FakeSSL:
        def __init__(self, host, port, timeout=None):
            calls["ssl"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            calls["login"] = user

        def send_message(self, msg):
            calls["sent_to"] = msg["To"]

    class FakePlain:
        def __init__(self, host, port, timeout=None):
            calls["plain"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, u, p):
            pass

        def send_message(self, m):
            pass

    _configure_smtp(monkeypatch, port=465)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP_SSL", FakeSSL)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP", FakePlain)

    r = SmtpEmailSender().send_email(
        subject="t", body="b", recipient="prospect@example.com"
    )
    assert r.success is True
    assert calls.get("ssl") == ("sgp14.siteground.asia", 465)
    assert "plain" not in calls
    assert calls.get("login") == "sales@alumcasting.com"
    assert calls.get("sent_to") == "prospect@example.com"


def test_starttls_used_on_port_587(monkeypatch):
    calls: dict = {}

    class FakePlain:
        def __init__(self, host, port, timeout=None):
            calls["plain"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, u, p):
            pass

        def send_message(self, m):
            pass

    class FakeSSL:
        def __init__(self, host, port, timeout=None):
            calls["ssl"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            pass

        def send_message(self, m):
            pass

    _configure_smtp(monkeypatch, port=587)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP_SSL", FakeSSL)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP", FakePlain)

    r = SmtpEmailSender().send_email(
        subject="t", body="b", recipient="prospect@example.com"
    )
    assert r.success is True
    assert calls.get("plain") == ("sgp14.siteground.asia", 587)
    assert calls.get("starttls") is True
    assert "ssl" not in calls


# ---------------------------------------------------------------------------
# Authentication failure handling
# ---------------------------------------------------------------------------
def test_smtp_auth_failure_handled(monkeypatch):
    class BadAuth:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(
                535, b"5.7.8 Username and Password not accepted"
            )

        def send_message(self, m):
            pass

    _configure_smtp(monkeypatch, port=465, password="wrong-password")
    monkeypatch.setattr(sender_mod.smtplib, "SMTP_SSL", BadAuth)

    r = SmtpEmailSender().send_email(
        subject="t", body="b", recipient="x@y.example"
    )
    assert r.success is False
    assert r.error is not None
    assert ("535" in r.error) or ("password" in r.error.lower())


# ---------------------------------------------------------------------------
# Mock fallback + provider factory
# ---------------------------------------------------------------------------
def test_get_email_sender_mock_fallback():
    assert isinstance(get_email_sender(), MockEmailSender)


def test_get_email_sender_smtp_when_configured(monkeypatch):
    _configure_smtp(monkeypatch, port=465)
    sender = get_email_sender()
    assert isinstance(sender, SmtpEmailSender)
    assert sender.from_email == "sales@alumcasting.com"


# ---------------------------------------------------------------------------
# GET /outreach/email-status
# ---------------------------------------------------------------------------
def test_email_status_unconfigured(client):
    r = client.get("/outreach/email-status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["provider"] == "mock"
    assert "password" not in json.dumps(body).lower()


def test_email_status_configured_shape(client, monkeypatch):
    _configure_smtp(monkeypatch, port=465)
    r = client.get("/outreach/email-status")
    assert r.status_code == 200
    assert r.json() == {
        "provider": "smtp",
        "configured": True,
        "sender_email": "sales@alumcasting.com",
        "smtp_host": "sgp14.siteground.asia",
        "smtp_port": 465,
        "use_ssl": True,
    }
    assert "password" not in json.dumps(r.json()).lower()


# ---------------------------------------------------------------------------
# POST /outreach/email-test
# ---------------------------------------------------------------------------
def test_email_test_mock_dry_run(client):
    r = client.post(
        "/outreach/email-test", json={"recipient": "test@example.com"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["provider"] == "mock"
    assert body["configured"] is False
    assert body["dry_run"] is True
    assert body["recipient"] == "test@example.com"
    assert body["sent_at"]


def test_email_test_invalid_recipient_422(client):
    r = client.post("/outreach/email-test", json={"recipient": "not-an-email"})
    assert r.status_code == 422


def test_email_test_default_recipient_and_real_provider(client, monkeypatch):
    class FakeSSL:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            pass

        def send_message(self, m):
            pass

    _configure_smtp(monkeypatch, port=465)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP_SSL", FakeSSL)

    # No recipient given -> defaults to SMTP_FROM_EMAIL.
    r = client.post("/outreach/email-test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["provider"] == "smtp"
    assert body["configured"] is True
    assert body["dry_run"] is False
    assert body["recipient"] == "sales@alumcasting.com"
