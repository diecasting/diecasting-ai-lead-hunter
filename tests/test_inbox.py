"""Phase 6 Stage 3: Reply Inbox Connector tests.

Covers email parsing (text + HTML fallback), lead matching priorities
(recipient → thread/subject → domain), duplicate prevention, the full
reply-automation pipeline, unmatched-email handling, the inbox APIs, and the
mock connector / provider factory.
"""
from app.crud import outreach as outreach_crud
from app.models.incoming_email import IncomingEmail
from app.models.lead import CompanyLead
from app.outreach.inbox import matcher, parser
from app.outreach.inbox.connector import InboxMessage, MockInboxConnector, get_inbox_connector


def _reset_mock():
    MockInboxConnector.queue = []
    MockInboxConnector.processed = []


def _make_lead(db, name, *, website=None, contact_email=None):
    lead = CompanyLead(name=name, website=website, contact_email=contact_email)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _make_sent(db, lead, subject, recipient_email=None):
    return outreach_crud.create(
        db,
        lead_id=lead.id,
        subject=subject,
        body="body",
        recipient_email=recipient_email,
        status="sent",
    )


# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------
def test_parse_email_text():
    raw = (
        b"From: Lena Fischer <l.fischer@acme-castings.example>\r\n"
        b"To: sales@leadhunter.example\r\n"
        b"Subject: Re: Partnership opportunity with Acme Castings\r\n"
        b"Date: Mon, 4 Aug 2026 09:00:00 +0200\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Please send us a quote, we have an open RFQ.\r\n"
    )
    msg = parser.parse_email(raw, external_id="42")
    assert msg.sender_email == "l.fischer@acme-castings.example"
    assert msg.sender_name == "Lena Fischer"
    assert msg.subject == "Re: Partnership opportunity with Acme Castings"
    assert "RFQ" in msg.body
    assert msg.external_id == "42"
    assert msg.received_at is not None


def test_parse_email_html_fallback_and_decoded_subject():
    raw = (
        b"From: omar@example.net\r\n"
        b"Subject: =?utf-8?B?UmU6IEhlbGxv?=\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="b"\r\n'
        b"\r\n"
        b"--b\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>Hi, <b>we are very interested</b>.<br>Please call us.</p></body></html>\r\n"
        b"--b--\r\n"
    )
    msg = parser.parse_email(raw)
    assert msg.sender_email == "omar@example.net"
    assert msg.subject == "Re: Hello"  # RFC-2047 decoded
    assert "we are very interested" in msg.body


# ---------------------------------------------------------------------------
# Matching priorities
# ---------------------------------------------------------------------------
def test_match_recipient_email_priority(db):
    lead = _make_lead(
        db, "Alpha Co", website="https://alpha.example.com",
        contact_email="buyer@alpha.example.com",
    )
    msg = _make_sent(
        db, lead, "Partnership opportunity with Alpha Co",
        recipient_email="buyer@alpha.example.com",
    )
    email = IncomingEmail(sender_email="buyer@alpha.example.com", subject="Re: X", body="hi")
    matched_lead, matched_msg = matcher.match_incoming_email(db, email)
    assert matched_lead.id == lead.id
    assert matched_msg.id == msg.id


def test_match_thread_subject_priority(db):
    lead = _make_lead(db, "Beta Co", website="https://beta.example.com")
    _make_sent(db, lead, "Project Alpha inquiry")
    email = IncomingEmail(sender_email="someone@x.example", subject="Re: Project Alpha inquiry", body="hi")
    matched_lead, matched_msg = matcher.match_incoming_email(db, email)
    assert matched_lead.id == lead.id
    assert matched_msg.subject == "Project Alpha inquiry"


def test_match_company_domain_priority(db):
    lead = _make_lead(db, "Gamma Co", website="https://gamma-castings.example.com")
    email = IncomingEmail(
        sender_email="purchasing@gamma-castings.example.com", subject="Hello", body="hi"
    )
    matched_lead, matched_msg = matcher.match_incoming_email(db, email)
    assert matched_lead.id == lead.id
    assert matched_msg is None


def test_match_unmatched(db):
    _make_lead(
        db, "Delta Co", website="https://delta.example.com",
        contact_email="d@delta.example.com",
    )
    email = IncomingEmail(sender_email="stranger@unknown-domain.example", subject="Hi", body="hi")
    assert matcher.match_incoming_email(db, email) is None


def test_normalize_subject():
    assert matcher.normalize_subject("Re: Fwd: hello") == "hello"
    assert matcher.normalize_subject("Re[2]: hello there") == "hello there"
    assert matcher.normalize_subject("hello") == "hello"


# ---------------------------------------------------------------------------
# Pipeline: duplicate prevention + reply automation
# ---------------------------------------------------------------------------
def test_pipeline_duplicate_prevention_and_automation(client, db):
    _reset_mock()
    lead = _make_lead(
        db, "Dup Co", website="https://dup.example.com",
        contact_email="buyer@dup.example.com",
    )
    MockInboxConnector.queue = [
        InboxMessage(
            sender_email="buyer@dup.example.com", subject="Re: Hello",
            body="Please send us a quote, we have an open RFQ.", external_id="1",
        ),
        InboxMessage(
            sender_email="buyer@dup.example.com", subject="Re: Hello",
            body="Please send us a quote, we have an open RFQ.", external_id="2",
        ),
    ]
    r = client.post("/outreach/inbox/process").json()
    assert r["fetched"] == 2
    assert r["new_emails"] == 1
    assert r["duplicates"] == 1
    assert r["matched"] == 1 and r["analyzed"] == 1

    # Idempotent re-run: the same email pushed again is a duplicate; nothing
    # new is processed and no second analysis is created.
    MockInboxConnector.queue = [
        InboxMessage(
            sender_email="buyer@dup.example.com", subject="Re: Hello",
            body="Please send us a quote, we have an open RFQ.", external_id="3",
        ),
    ]
    r2 = client.post("/outreach/inbox/process").json()
    assert r2["fetched"] == 1 and r2["duplicates"] == 1 and r2["matched"] == 0

    db.expire_all()
    from app.models.reply_analysis import ReplyAnalysis

    assert db.query(ReplyAnalysis).count() == 1
    assert client.get(f"/leads/{lead.id}").json()["lead_status"] == "rfq"


def test_pipeline_matched_email_and_inbox_apis(client, db):
    _reset_mock()
    lead = _make_lead(
        db, "Auto Co", website="https://auto.example.com",
        contact_email="buyer@auto.example.com",
    )
    msg = _make_sent(
        db, lead, "Partnership opportunity with Auto Co",
        recipient_email="buyer@auto.example.com",
    )
    MockInboxConnector.queue = [
        InboxMessage(
            sender_email="buyer@auto.example.com", sender_name="Auto Buyer",
            subject="Re: Partnership opportunity with Auto Co",
            body="We are very interested, please schedule a call.", external_id="7",
        ),
    ]
    r = client.post("/outreach/inbox/process").json()
    assert r == {
        "fetched": 1, "new_emails": 1, "duplicates": 0,
        "processed": 1, "matched": 1, "unmatched": 0, "analyzed": 1,
    }

    rows = client.get("/outreach/inbox").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["processed"] is True
    assert row["matched_lead_id"] == lead.id
    assert row["matched_lead_name"] == "Auto Co"
    assert row["message_id"] == msg.id
    assert row["analysis_id"] is not None
    assert row["intent"] == "interested"
    assert row["confidence_score"] is not None
    assert row["recommended_action"]
    assert client.get("/outreach/inbox?processed=false").json() == []
    assert client.get("/outreach/inbox/unprocessed").json() == []
    # CRM automation applied via the reply intelligence engine.
    assert client.get(f"/leads/{lead.id}").json()["lead_status"] == "qualified"
    # The connector was told to mark the message processed in the mailbox.
    assert "7" in MockInboxConnector.processed


def test_pipeline_unmatched_email_handling(client, db):
    _reset_mock()
    MockInboxConnector.queue = [
        InboxMessage(
            sender_email="spammer@unknown.example", subject="Hello",
            body="Buy our stuff", external_id="9",
        ),
    ]
    r = client.post("/outreach/inbox/process").json()
    assert r["processed"] == 1 and r["unmatched"] == 1 and r["matched"] == 0

    un = client.get("/outreach/inbox/unprocessed").json()
    assert len(un) == 1
    assert un[0]["sender_email"] == "spammer@unknown.example"
    assert un[0]["processed"] is False
    assert un[0]["intent"] is None
    assert un[0]["matched_lead_id"] is None
    # Still listed with processed=false in the full inbox view.
    assert client.get("/outreach/inbox").json()[0]["processed"] is False


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
def test_mock_connector_fetch_and_mark():
    _reset_mock()
    m = MockInboxConnector()
    assert m.fetch_new_messages() == []
    MockInboxConnector.queue = [InboxMessage(sender_email="a@b.c", body="x", external_id="1")]
    msgs = MockInboxConnector().fetch_new_messages()
    assert len(msgs) == 1 and msgs[0].sender_email == "a@b.c"
    m.mark_processed("1")
    assert "1" in MockInboxConnector.processed


def test_get_inbox_connector_factory(monkeypatch):
    from app import config as config_mod

    # Hermetic: clear any real IMAP credentials from a local .env.
    monkeypatch.setattr(config_mod.settings, "imap_host", "")
    monkeypatch.setattr(config_mod.settings, "imap_username", "")
    monkeypatch.setattr(config_mod.settings, "imap_password", "")

    _reset_mock()
    assert isinstance(get_inbox_connector(), MockInboxConnector)  # unconfigured
    monkeypatch.setattr(config_mod.settings, "imap_host", "imap.example.com")
    monkeypatch.setattr(config_mod.settings, "imap_username", "user@example.com")
    monkeypatch.setattr(config_mod.settings, "imap_password", "secret")
    conn = get_inbox_connector()
    assert conn.__class__.__name__ == "ImapInboxConnector"
    assert conn.host == "imap.example.com" and conn.folder == "INBOX"
