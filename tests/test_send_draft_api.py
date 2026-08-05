"""Phase 4 Stage 5 — Email Sending Pipeline tests.

Covers the POST /outreach/drafts/{id}/send endpoint and the EmailSender
abstraction:

  * a ready draft sends successfully (mock provider records the send,
    send_status advances draft -> queued -> sent, sent_at populated)
  * review / blocked drafts are rejected (422)
  * missing / malformed recipient_email is rejected (422)
  * an SMTP delivery failure is handled (200 + success=false, send_status
    becomes "failed")
  * the mock provider records sends and can simulate failures

No real SMTP connection is ever made (mock provider / injected transport).
"""
from fastapi.testclient import TestClient

from app.outreach.sender import MockEmailSender, get_email_sender, SmtpEmailSender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_draft(client, *, contact_email=None):
    """Create a lead (optionally with email), generate a draft, return ids."""
    payload = {
        "name": f"SendTest {contact_email or 'NoMail'}",
        "website": f"https://sendtest-{abs(hash(contact_email or 'x'))}.example.com",
        "industry": "automotive",
        "materials": "aluminum",
        "manufacturing_process": "high pressure die casting",
        "contact_role": "Purchasing Manager",
    }
    if contact_email:
        payload["contact_email"] = contact_email
    lead = client.post("/leads", json=payload)
    assert lead.status_code == 201
    lead_id = lead.json()["id"]
    gen = client.post(f"/leads/{lead_id}/generate-email")
    assert gen.status_code == 201
    return lead_id, gen.json()["id"]


def _set_gate(client, message_id, gate):
    r = client.patch(f"/outreach/drafts/{message_id}/gate", json={"gate_status": gate})
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Send rules
# ---------------------------------------------------------------------------
def test_ready_draft_sends_successfully(client: TestClient, db):
    lead_id, msg_id = _make_draft(client, contact_email="buyer@sendapi.com")
    _set_gate(client, msg_id, "ready")

    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["message_id"] == msg_id
    assert body["sent_at"] is not None
    assert body["send_status"] == "sent"

    # Message moved to sent in the pipeline.
    messages = client.get(f"/outreach/leads/{lead_id}/messages").json()
    sent = [m for m in messages if m["id"] == msg_id][0]
    assert sent["status"] == "sent"
    assert sent["send_status"] == "sent"
    assert sent["sent_at"] is not None
    assert sent["recipient"] == "buyer@sendapi.com"


def test_review_draft_rejected(client: TestClient):
    _, msg_id = _make_draft(client, contact_email="buyer@review.com")
    _set_gate(client, msg_id, "review")
    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 422
    assert "quality gate must be 'ready'" in r.json()["detail"]


def test_blocked_draft_rejected(client: TestClient):
    _, msg_id = _make_draft(client, contact_email="buyer@blocked.com")
    _set_gate(client, msg_id, "blocked")
    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 422
    assert "quality gate must be 'ready'" in r.json()["detail"]


def test_missing_recipient_email_rejected(client: TestClient):
    _, msg_id = _make_draft(client, contact_email=None)
    _set_gate(client, msg_id, "ready")
    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 422
    assert "recipient_email is required" in r.json()["detail"]


def test_invalid_recipient_email_rejected(client: TestClient):
    _, msg_id = _make_draft(client, contact_email="not-an-email")
    _set_gate(client, msg_id, "ready")
    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 422
    assert "invalid recipient email" in r.json()["detail"]


def test_send_unknown_message_404(client: TestClient):
    r = client.post("/outreach/drafts/999999/send")
    assert r.status_code == 404


def test_failed_smtp_handled_correctly(client: TestClient, db, monkeypatch):
    """A delivery failure must not 500: success=false + send_status=failed."""
    lead_id, msg_id = _make_draft(client, contact_email="buyer@fail.com")
    _set_gate(client, msg_id, "ready")

    failing = MockEmailSender()
    failing.fail_on = "connection refused (simulated)"
    monkeypatch.setattr("app.api.outreach.get_email_sender", lambda: failing)

    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["send_status"] == "failed"
    assert "connection refused" in (body["error"] or "")

    messages = client.get(f"/outreach/leads/{lead_id}/messages").json()
    msg = [m for m in messages if m["id"] == msg_id][0]
    assert msg["send_status"] == "failed"
    assert msg["status"] == "draft"  # never marked sent


# ---------------------------------------------------------------------------
# EmailSender abstraction
# ---------------------------------------------------------------------------
def test_get_email_sender_returns_mock_without_smtp_config(monkeypatch):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "smtp_host", "")
    monkeypatch.setattr(config_mod.settings, "smtp_user", "")
    monkeypatch.setattr(config_mod.settings, "smtp_username", "")
    monkeypatch.setattr(config_mod.settings, "smtp_password", "")
    sender = get_email_sender()
    assert isinstance(sender, MockEmailSender)


def test_get_email_sender_returns_smtp_when_configured(monkeypatch):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(config_mod.settings, "smtp_username", "user@example.com")
    monkeypatch.setattr(config_mod.settings, "smtp_password", "secret")
    sender = get_email_sender()
    assert isinstance(sender, SmtpEmailSender)
    # SMTP_USERNAME is the canonical credential env name read by the provider.
    assert config_mod.settings.smtp_username == "user@example.com"


def test_mock_provider_records_send_and_validate():
    sender = MockEmailSender()
    assert sender.validate_recipient("") == "recipient_email is required"
    assert sender.validate_recipient("nope") is not None
    assert sender.validate_recipient("ok@example.com") is None

    receipt = sender.send_email(
        subject="S", body="B", recipient="ok@example.com", sender="from@mock.local"
    )
    assert receipt.success is True
    assert receipt.sent_at
    assert len(sender.sent) == 1
    assert sender.sent[0].recipient == "ok@example.com"
    assert receipt.to_dict()["recipient"] == "ok@example.com"

    sender.fail_on = "boom"
    failed = sender.send_email(subject="S", body="B", recipient="ok@example.com")
    assert failed.success is False
    assert failed.error == "boom"
