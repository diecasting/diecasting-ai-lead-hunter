"""Phase 6 Stage 4: IMAP inbox connector (SiteGround) configuration tests.

Covers IMAP provider selection, the SSL connection path (IMAP4_SSL on 993),
authentication failure handling, the mock fallback, the new
``GET /outreach/inbox/status`` + ``POST /outreach/inbox/test`` endpoints
(no password exposure), and that inbox processing stays unchanged (incl. the
connector-fetch error guard).
"""
import json

import imaplib
import pytest

from app.outreach.inbox import connector as inbox_connector
from app.outreach.inbox.connector import (
    ImapInboxConnector,
    MockInboxConnector,
    get_inbox_connector,
    imap_configured,
)


def _configure_imap(monkeypatch, *, password="secret"):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "imap_host", "sgp14.siteground.asia")
    monkeypatch.setattr(config_mod.settings, "imap_port", 993)
    monkeypatch.setattr(config_mod.settings, "imap_username", "sales@alumcasting.com")
    monkeypatch.setattr(config_mod.settings, "imap_password", password)
    monkeypatch.setattr(config_mod.settings, "imap_use_ssl", True)
    monkeypatch.setattr(config_mod.settings, "imap_folder", "INBOX")


# ---------------------------------------------------------------------------
# Provider selection + SSL connection
# ---------------------------------------------------------------------------
def test_imap_provider_selection(monkeypatch):
    from app import config as config_mod

    # Hermetic: clear any real IMAP credentials from a local .env.
    monkeypatch.setattr(config_mod.settings, "imap_host", "")
    monkeypatch.setattr(config_mod.settings, "imap_username", "")
    monkeypatch.setattr(config_mod.settings, "imap_password", "")
    assert isinstance(get_inbox_connector(), MockInboxConnector)  # unconfigured
    assert imap_configured() is False

    _configure_imap(monkeypatch)
    conn = get_inbox_connector()
    assert isinstance(conn, ImapInboxConnector)
    assert conn.host == "sgp14.siteground.asia"
    assert conn.port == 993
    assert conn.use_ssl is True
    assert conn.folder == "INBOX"
    assert imap_configured() is True


def test_imap_ssl_connection_and_count(monkeypatch):
    calls: dict = {}

    class FakeIMAP4SSL:
        def __init__(self, host, port):
            calls["ssl"] = (host, port)

        def login(self, user, password):
            calls["login"] = (user, password)

        def select(self, folder):
            calls["folder"] = folder
            return ("OK", [b"3"])

        def search(self, charset, criteria):
            calls["search"] = criteria
            return ("OK", [b"1 2 3"])

        def fetch(self, num, parts):
            calls.setdefault("fetch", []).append(num)
            raw = b"From: buyer@example.com\r\nSubject: Re: Hello\r\n\r\nbody\r\n"
            return ("OK", [(num, raw)])

        def logout(self):
            calls["logout"] = True

    class FakeIMAP4:
        def __init__(self, host, port):
            calls["plain"] = (host, port)

        def login(self, u, p):
            pass

        def logout(self):
            pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP4SSL)
    monkeypatch.setattr(imaplib, "IMAP4", FakeIMAP4)

    conn = ImapInboxConnector(
        host="sgp14.siteground.asia",
        port=993,
        username="sales@alumcasting.com",
        password="secret",
        use_ssl=True,
        folder="INBOX",
    )
    res = conn.test_connection()
    assert res["ok"] is True
    assert calls["ssl"] == ("sgp14.siteground.asia", 993)
    assert "plain" not in calls
    assert calls["login"] == ("sales@alumcasting.com", "secret")
    assert calls["folder"] == "INBOX"
    assert calls["search"] == "ALL"
    assert res["count"] == 3
    assert len(res["latest"]) == 3
    assert res["latest"][0]["sender_email"] == "buyer@example.com"


def test_imap_auth_failure_handled(monkeypatch):
    class BadAuth:
        def __init__(self, host, port):
            pass

        def login(self, user, password):
            raise imaplib.IMAP4.error("LOGIN failed")

        def logout(self):
            pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", BadAuth)

    conn = ImapInboxConnector(
        host="sgp14.siteground.asia",
        port=993,
        username="sales@alumcasting.com",
        password="wrong",
        use_ssl=True,
    )
    res = conn.test_connection()
    assert res["ok"] is False
    assert "LOGIN" in res["error"]
    assert res["count"] == 0


# ---------------------------------------------------------------------------
# Inbox processing unchanged + fetch error guard
# ---------------------------------------------------------------------------
def test_process_inbox_fetch_error_guarded(client, db, monkeypatch):
    from app.outreach.inbox import processor as processor_mod

    class BoomConnector:
        def fetch_new_messages(self):
            raise RuntimeError("imap down")

        def mark_processed(self, external_id):
            pass

    monkeypatch.setattr(processor_mod, "get_inbox_connector", lambda: BoomConnector())
    summary = processor_mod.process_inbox(db)
    assert "error" in summary and "imap down" in summary["error"]
    assert summary["fetched"] == 0


def test_inbox_processing_unchanged_with_mock(client, db):
    """The pipeline still works end-to-end via the mock connector."""
    from app.models.incoming_email import IncomingEmail
    from app.models.lead import CompanyLead
    from app.outreach.inbox.connector import InboxMessage, MockInboxConnector

    MockInboxConnector.queue = []
    MockInboxConnector.processed = []

    lead = CompanyLead(
        name="ImapCo", website="https://imapco.example.com",
        contact_email="buyer@imapco.example.com",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    MockInboxConnector.queue = [
        InboxMessage(
            sender_email="buyer@imapco.example.com",
            subject="Re: Hi",
            body="Please send us a quote, we have an open RFQ.",
            external_id="1",
        )
    ]
    r = client.post("/outreach/inbox/process").json()
    assert r["matched"] == 1 and r["analyzed"] == 1
    assert client.get(f"/leads/{lead.id}").json()["lead_status"] == "rfq"


# ---------------------------------------------------------------------------
# GET /outreach/inbox/status
# ---------------------------------------------------------------------------
def test_inbox_status_mock_fallback(client):
    r = client.get("/outreach/inbox/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["configured"] is False
    assert "password" not in json.dumps(body).lower()


def test_inbox_status_configured_shape(client, monkeypatch):
    _configure_imap(monkeypatch)
    r = client.get("/outreach/inbox/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "imap"
    assert body["configured"] is True
    assert body["server"] == "sgp14.siteground.asia"
    assert body["username"] == "sales@alumcasting.com"
    assert body["folder"] == "INBOX"
    assert body["use_ssl"] is True
    assert body["fetched_count"] >= 0
    assert "password" not in json.dumps(body).lower()


# ---------------------------------------------------------------------------
# POST /outreach/inbox/test
# ---------------------------------------------------------------------------
def test_inbox_test_mock_dry_run(client):
    r = client.post("/outreach/inbox/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "mock"
    assert body["configured"] is False
    assert "dry-run" in body["message"]


def test_inbox_test_imap_path(client, monkeypatch):
    calls: dict = {}

    class FakeIMAP4SSL:
        def __init__(self, host, port):
            calls["ssl"] = (host, port)

        def login(self, user, password):
            calls["login"] = user

        def select(self, folder):
            return ("OK", [b"1"])

        def search(self, charset, criteria):
            return ("OK", [b"1 2"])

        def fetch(self, num, parts):
            raw = b"From: x@y.example\r\nSubject: Re: Part\r\n\r\nhi\r\n"
            return ("OK", [(num, raw)])

        def logout(self):
            pass

    _configure_imap(monkeypatch)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP4SSL)

    r = client.post("/outreach/inbox/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "imap"
    assert body["configured"] is True
    assert body["count"] == 2
    assert len(body["latest"]) == 2
    assert calls["ssl"] == ("sgp14.siteground.asia", 993)
