"""Tests for Phase 3 Stage 1 CRM data-model upgrade.

Covers:
* model creation (ORM round-trips for the 6 new tables + extended columns),
* Alembic migration 0005 upgrade (skips if ``alembic`` is not installed),
* API CRUD for the new ``/crm-data`` endpoints.
"""
import importlib.util
import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.contact import Contact
from app.models.lead import CompanyLead
from app.models.lead_source import LeadSource
from app.models.email_verification import EmailVerification
from app.models.email_tracking import EmailTracking
from app.models.outreach_message import OutreachMessage
from app.models.reply_inbox import ReplyInbox
from app.models.unsubscribe import Unsubscribe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def lead(db):
    obj = CompanyLead(
        name="CRM Test Co", website="https://crm-test.com", domain="crm-test.com"
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture
def message(db, lead):
    obj = OutreachMessage(lead_id=lead.id, subject="Hi", body="Body")
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ---------------------------------------------------------------------------
# Model creation
# ---------------------------------------------------------------------------
class TestModelCreation:
    def test_contact_columns(self, db, lead):
        c = Contact(lead_id=lead.id, email="buyer@crm-test.com", role="Purchasing", is_primary=True)
        db.add(c)
        db.commit()
        db.refresh(c)
        assert c.id
        assert c.do_not_contact is False
        assert c.is_primary is True

    def test_lead_source_columns(self, db):
        s = LeadSource(name="google_search", description="Google SERP")
        db.add(s)
        db.commit()
        db.refresh(s)
        assert s.name == "google_search"
        assert s.is_active is True

    def test_email_verification_columns(self, db, lead):
        v = EmailVerification(lead_id=lead.id, email="x@crm-test.com", status="valid",
                              is_deliverable="yes")
        db.add(v)
        db.commit()
        db.refresh(v)
        assert v.status == "valid"
        assert v.is_deliverable == "yes"

    def test_email_tracking_columns(self, db, message):
        t = EmailTracking(message_id=message.id, event_type="open", tracking_token="tok123")
        db.add(t)
        db.commit()
        db.refresh(t)
        assert t.event_type == "open"
        # Aggregated counter on the parent message is maintained by CRUD layer;
        # the model itself just stores the event.
        assert t.message_id == message.id

    def test_reply_inbox_columns(self, db, lead):
        r = ReplyInbox(lead_id=lead.id, from_email="x@crm-test.com", subject="Re:", is_bounce=False)
        db.add(r)
        db.commit()
        db.refresh(r)
        assert r.is_bounce is False
        assert r.from_email == "x@crm-test.com"

    def test_unsubscribe_columns(self, db, lead):
        u = Unsubscribe(lead_id=lead.id, email="x@crm-test.com", reason="no interest", token="u-tok")
        db.add(u)
        db.commit()
        db.refresh(u)
        assert u.email == "x@crm-test.com"

    def test_company_lead_extensions(self, db):
        l = CompanyLead(
            name="Ext Co",
            do_not_contact=True,
            bounce_count=3,
            acquisition_channel="linkedin",
        )
        db.add(l)
        db.commit()
        db.refresh(l)
        assert l.do_not_contact is True
        assert l.bounce_count == 3
        assert l.acquisition_channel == "linkedin"

    def test_outreach_message_extensions(self, db, lead):
        m = OutreachMessage(
            lead_id=lead.id,
            subject="S",
            body="B",
            tracking_token="track-1",
            open_count=2,
            click_count=1,
            html_body="<p>B</p>",
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        assert m.tracking_token == "track-1"
        assert m.open_count == 2
        assert m.click_count == 1
        assert m.html_body == "<p>B</p>"


# ---------------------------------------------------------------------------
# Migration upgrade (0005)
# ---------------------------------------------------------------------------
def test_migration_0005_creates_tables(tmp_path, monkeypatch):
    if importlib.util.find_spec("alembic") is None:
        pytest.skip("alembic not installed in this environment")
    db_path = tmp_path / "migrated.db"
    db_url = f"sqlite:///{db_path}"

    import app.config as config_mod

    monkeypatch.setattr(config_mod.settings, "database_url", db_url)

    from alembic import command
    from alembic.config import Config

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "contacts",
        "lead_sources",
        "email_verifications",
        "email_tracking",
        "reply_inbox",
        "unsubscribes",
    }
    assert expected.issubset(tables), f"missing tables: {expected - tables}"

    # company_leads + outreach_messages gained the new columns.
    cl_cols = {c["name"] for c in inspector.get_columns("company_leads")}
    om_cols = {c["name"] for c in inspector.get_columns("outreach_messages")}
    assert {"do_not_contact", "bounce_count", "acquisition_channel"}.issubset(cl_cols)
    assert {"tracking_token", "open_count", "click_count", "html_body"}.issubset(om_cols)


# ---------------------------------------------------------------------------
# API CRUD
# ---------------------------------------------------------------------------
class TestCrmDataApi:
    def _make_lead(self, client):
        resp = client.post(
            "/leads",
            json={"name": "ApiCRM Co", "website": "https://api-crm.com", "domain": "api-crm.com"},
        )
        return resp.json()["id"]

    def test_contact_crud(self, client):
        lead_id = self._make_lead(client)
        # create
        resp = client.post(
            "/crm-data/contacts",
            json={"lead_id": lead_id, "email": "buyer@api-crm.com", "role": "Purchasing", "is_primary": True},
        )
        assert resp.status_code == 201, resp.text
        cid = resp.json()["id"]
        # get
        resp = client.get(f"/crm-data/contacts/{cid}")
        assert resp.status_code == 200
        assert resp.json()["email"] == "buyer@api-crm.com"
        # list by lead
        resp = client.get(f"/crm-data/leads/{lead_id}/contacts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        # update
        resp = client.patch(f"/crm-data/contacts/{cid}", json={"do_not_contact": True})
        assert resp.status_code == 200
        assert resp.json()["do_not_contact"] is True
        # delete
        resp = client.delete(f"/crm-data/contacts/{cid}")
        assert resp.status_code == 204
        resp = client.get(f"/crm-data/contacts/{cid}")
        assert resp.status_code == 404

    def test_lead_source_crud(self, client):
        resp = client.post("/crm-data/lead-sources", json={"name": "trade_show", "description": "Expo"})
        assert resp.status_code == 201, resp.text
        sid = resp.json()["id"]
        # duplicate name -> 409
        resp = client.post("/crm-data/lead-sources", json={"name": "trade_show"})
        assert resp.status_code == 409
        # list
        resp = client.get("/crm-data/lead-sources")
        assert resp.status_code == 200
        assert any(s["name"] == "trade_show" for s in resp.json())
        # get
        resp = client.get(f"/crm-data/lead-sources/{sid}")
        assert resp.status_code == 200
        # update
        resp = client.patch(f"/crm-data/lead-sources/{sid}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        # delete
        resp = client.delete(f"/crm-data/lead-sources/{sid}")
        assert resp.status_code == 204

    def test_email_verification_crud(self, client):
        lead_id = self._make_lead(client)
        resp = client.post(
            "/crm-data/email-verifications",
            json={"lead_id": lead_id, "email": "v@api-crm.com", "status": "valid"},
        )
        assert resp.status_code == 201, resp.text
        vid = resp.json()["id"]
        resp = client.get(f"/crm-data/email-verifications/{vid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "valid"
        resp = client.get(f"/crm-data/leads/{lead_id}/email-verifications")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_email_tracking_crud(self, client):
        lead_id = self._make_lead(client)
        # need a message to attach tracking to
        client.post(f"/leads/{lead_id}/generate-email")
        from app.crud import outreach as oc
        # use db fixture indirectly via a fresh session through the API is not
        # possible; create message directly via the existing generate endpoint
        # then read its id from the list endpoint
        msgs = client.get(f"/outreach/leads/{lead_id}/messages").json()
        message_id = msgs[0]["id"]
        resp = client.post(
            "/crm-data/email-tracking",
            json={"message_id": message_id, "event_type": "open", "tracking_token": "t1"},
        )
        assert resp.status_code == 201, resp.text
        tid = resp.json()["id"]
        # invalid event_type -> 400
        resp = client.post(
            "/crm-data/email-tracking",
            json={"message_id": message_id, "event_type": "bounce"},
        )
        assert resp.status_code == 400
        # list for message
        resp = client.get(f"/crm-data/messages/{message_id}/email-tracking")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_reply_inbox_crud(self, client):
        lead_id = self._make_lead(client)
        resp = client.post(
            "/crm-data/reply-inbox",
            json={"lead_id": lead_id, "from_email": "r@api-crm.com", "subject": "Re:", "is_bounce": False},
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]
        resp = client.get(f"/crm-data/reply-inbox/{rid}")
        assert resp.status_code == 200
        # list all
        resp = client.get("/crm-data/reply-inbox")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_unsubscribe_crud(self, client):
        lead_id = self._make_lead(client)
        resp = client.post(
            "/crm-data/unsubscribes",
            json={"lead_id": lead_id, "email": "u@api-crm.com", "reason": "no thanks"},
        )
        assert resp.status_code == 201, resp.text
        uid = resp.json()["id"]
        resp = client.get(f"/crm-data/unsubscribes/{uid}")
        assert resp.status_code == 200
        resp = client.get(f"/crm-data/leads/{lead_id}/unsubscribes")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_lead_extended_fields_in_read(self, client):
        resp = client.post(
            "/leads",
            json={
                "name": "ExtRead Co",
                "website": "https://extread.com",
                "do_not_contact": True,
                "bounce_count": 2,
                "acquisition_channel": "referral",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["do_not_contact"] is True
        assert body["bounce_count"] == 2
        assert body["acquisition_channel"] == "referral"
