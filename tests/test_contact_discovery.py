"""Phase 13.1 — Contact Discovery Foundation.

Covers:
  * ContactDiscoveryLog model creation + vocabulary
  * FK CASCADE behaviour (deleting the lead removes its discovery log)
  * discovery_method defaults on EmailAddress / Contact
  * index presence on the new table / columns
  * no regression to the existing Email Discovery engine
"""
from datetime import datetime, timezone

from sqlalchemy import inspect

from app.models.contact_discovery_log import (
    ContactDiscoveryLog,
    DISCOVERY_METHOD_WEBSITE,
    DISCOVERY_METHOD_PDF,
    DISCOVERY_METHOD_PATTERN,
    DISCOVERY_METHOD_EXTERNAL,
    DISCOVERY_METHODS,
    DISCOVERY_STATUS_DONE,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_SKIPPED,
    DISCOVERY_STATUSES,
)
from app.models.email_address import EmailAddress
from app.models.contact import Contact
from app.models.lead import CompanyLead


# ---------------------------------------------------------------------------
# ContactDiscoveryLog
# ---------------------------------------------------------------------------
def test_discovery_log_creation(db):
    lead = CompanyLead(name="Acme Castings")
    db.add(lead)
    db.commit()

    log = ContactDiscoveryLog(
        company_id=lead.id,
        domain="acme.com",
        method=DISCOVERY_METHOD_WEBSITE,
        contacts_found=3,
        emails_found=5,
        status=DISCOVERY_STATUS_DONE,
        detail="homepage + contact page",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    assert log.id is not None
    assert log.company_id == lead.id
    assert log.domain == "acme.com"
    assert log.method == DISCOVERY_METHOD_WEBSITE
    assert log.contacts_found == 3
    assert log.emails_found == 5
    assert log.status == DISCOVERY_STATUS_DONE
    assert isinstance(log.scanned_at, datetime)
    assert isinstance(log.created_at, datetime)


def test_discovery_log_defaults(db):
    lead = CompanyLead(name="Beta Forgings")
    db.add(lead)
    db.commit()

    log = ContactDiscoveryLog(company_id=lead.id, domain="beta.com")
    db.add(log)
    db.commit()
    db.refresh(log)

    assert log.method == DISCOVERY_METHOD_WEBSITE
    assert log.status == DISCOVERY_STATUS_DONE
    assert log.contacts_found == 0
    assert log.emails_found == 0


def test_discovery_method_vocabulary():
    assert DISCOVERY_METHODS == [
        DISCOVERY_METHOD_WEBSITE,
        DISCOVERY_METHOD_PDF,
        DISCOVERY_METHOD_PATTERN,
        DISCOVERY_METHOD_EXTERNAL,
    ]
    assert DISCOVERY_STATUSES == [
        DISCOVERY_STATUS_DONE,
        DISCOVERY_STATUS_FAILED,
        DISCOVERY_STATUS_SKIPPED,
    ]


def test_discovery_log_fk_cascade(db):
    lead = CompanyLead(name="Gamma Tools")
    db.add(lead)
    db.commit()

    log = ContactDiscoveryLog(company_id=lead.id, domain="gamma.com")
    db.add(log)
    db.commit()
    log_id = log.id
    db.commit()

    # Deleting the owning company must cascade-remove its discovery history.
    db.delete(lead)
    db.commit()

    remaining = (
        db.query(ContactDiscoveryLog)
        .filter(ContactDiscoveryLog.id == log_id)
        .first()
    )
    assert remaining is None


def test_discovery_log_indexes_exist(db):
    insp = inspect(db.bind)
    indexes = insp.get_indexes("contact_discovery_logs")
    index_columns = {tuple(ix["column_names"]) for ix in indexes}
    # (company_id, method) composite for skip-by-method lookups.
    assert ("company_id", "method") in index_columns
    # domain + company_id covered individually.
    assert ("domain",) in index_columns
    assert ("company_id",) in index_columns


# ---------------------------------------------------------------------------
# discovery_method provenance columns
# ---------------------------------------------------------------------------
def test_email_address_discovery_method_default(db):
    lead = CompanyLead(name="Delta Molds")
    db.add(lead)
    db.commit()

    addr = EmailAddress(company_id=lead.id, email="sales@delta.com")
    db.add(addr)
    db.commit()
    db.refresh(addr)

    assert addr.discovery_method == DISCOVERY_METHOD_WEBSITE


def test_email_address_discovery_method_explicit(db):
    lead = CompanyLead(name="Epsilon Press")
    db.add(lead)
    db.commit()

    addr = EmailAddress(
        company_id=lead.id,
        email="purchasing@epsilon.com",
        discovery_method=DISCOVERY_METHOD_PATTERN,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)

    assert addr.discovery_method == DISCOVERY_METHOD_PATTERN


def test_contact_discovery_method_default(db):
    lead = CompanyLead(name="Zeta Stamping")
    db.add(lead)
    db.commit()

    contact = Contact(lead_id=lead.id, full_name="Jane Buyer", email="jane@zeta.com")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    assert contact.discovery_method == DISCOVERY_METHOD_WEBSITE


def test_contact_discovery_method_explicit(db):
    lead = CompanyLead(name="Eta Coatings")
    db.add(lead)
    db.commit()

    contact = Contact(
        lead_id=lead.id,
        full_name="John Eng",
        email="john@eta.com",
        discovery_method=DISCOVERY_METHOD_PDF,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    assert contact.discovery_method == DISCOVERY_METHOD_PDF


def test_discovery_method_index_exists(db):
    insp = inspect(db.bind)
    ea_indexes = insp.get_indexes("email_addresses")
    ea_cols = {tuple(ix["column_names"]) for ix in ea_indexes}
    assert ("discovery_method",) in ea_cols

    c_indexes = insp.get_indexes("contacts")
    c_cols = {tuple(ix["column_names"]) for ix in c_indexes}
    assert ("discovery_method",) in c_cols


# ---------------------------------------------------------------------------
# No regression to the existing Email Discovery engine
# ---------------------------------------------------------------------------
def test_email_discovery_engine_still_importable():
    # The Phase 13.1 foundation must not break the existing module surface.
    from app.email_discovery import patterns as pat
    from app.email_discovery import ranking as rnk
    from app.email_discovery.extractor import WebsiteEmailCrawler
    from app.email_discovery.verification import verify_email_address

    assert pat.classify_email_type("sales@example.com") == "role"
    assert pat.classify_email_type("john.smith@example.com") == "personal"
    # Pattern inference + ranking still behave deterministically.
    out = pat.generate_pattern_emails(
        ["first.last", "first"], "John", "Smith", domain="example.com"
    )
    assert "john.smith@example.com" in out
    assert rnk.rank_score("john.smith@example.com", email_type="personal") > rnk.rank_score(
        "sales@example.com", email_type="role"
    )
