"""Phase 13.2 — Contact Discovery Engine.

Covers the four discovery sources and the supporting machinery, all offline
(no network, no LLM):

  * deterministic ``discovery_score`` + ``confidence`` classification
  * role-inbox generation (``generate_role_inbox_emails``)
  * website contact extraction (named people + bare on-domain mailboxes)
  * PDF contact extraction (off-domain / customer e-mails rejected)
  * contact <-> e-mail linking (EmailAddress upsert + email_address_id)
  * regression: per-name e-mail association (no more global emails[0])
  * duplicate prevention across runs
  * TTL skip check via ContactDiscoveryLog
  * the three new ``contacts`` columns exist (indexed)
"""
from datetime import datetime, timezone
from sqlalchemy import inspect

from app.contact_discovery.role_patterns import (
    generate_role_inbox_emails,
    role_inbox_category,
    role_inbox_label,
)
from app.contact_discovery.scoring import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    classify_confidence,
    score_discovery,
)
from app.contact_discovery.service import ContactDiscoveryService
from app.crawler.contact_extractor import extract_contacts
from app.crud import contacts as contacts_crud
from app.models.contact import SOURCE_EMAIL_PATTERN
from app.models.contact_discovery_log import (
    DISCOVERY_METHOD_PATTERN,
    DISCOVERY_METHOD_WEBSITE,
    DISCOVERY_STATUS_DONE,
    ContactDiscoveryLog,
)
from app.models.lead import CompanyLead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_lead(db, website="https://acme.com"):
    lead = CompanyLead(name="Acme Castings", website=website)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _seen_sets(db, lead):
    existing = contacts_crud.list_for_lead(db, lead.id)
    return (
        {c.email.lower() for c in existing if c.email},
        {c.full_name for c in existing if c.full_name},
    )


# ---------------------------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------------------------
def test_score_discovery_valid_procurement_website_is_high():
    score = score_discovery(
        verification_status="valid",
        source="website",
        title_category="procurement",
        has_email=True,
    )
    assert score == 75  # 30 + 20 + 25
    assert classify_confidence(score) == CONFIDENCE_HIGH


def test_score_discovery_unverified_pdf_engineering_is_low():
    score = score_discovery(
        verification_status=None,
        source="pdf",
        title_category="engineering",
        has_email=True,
    )
    assert score == 33  # 0 + 15 + 18
    assert classify_confidence(score) == CONFIDENCE_LOW


def test_score_discovery_pattern_role_inbox():
    score = score_discovery(
        verification_status=None,
        source="pattern",
        title_category="procurement",
        is_pattern=True,
        has_email=True,
    )
    assert score == 35  # 0 + 5 + 25 + 5
    assert classify_confidence(score) == CONFIDENCE_LOW


def test_score_discovery_no_email_is_capped():
    score = score_discovery(
        verification_status="valid",
        source="website",
        title_category="procurement",
        has_email=False,
    )
    # 30 + 20 + 25 = 75, capped at 40 because there is no deliverable e-mail.
    assert score == 40
    assert classify_confidence(score) == CONFIDENCE_LOW


def test_score_discovery_is_deterministic():
    kwargs = dict(
        verification_status="risky",
        source="website",
        title_category="sales",
        is_pattern=False,
        has_email=True,
    )
    assert score_discovery(**kwargs) == score_discovery(**kwargs)


# ---------------------------------------------------------------------------
# Role-inbox generation
# ---------------------------------------------------------------------------
def test_generate_role_inbox_emails():
    emails = generate_role_inbox_emails("acme.com")
    assert len(emails) == 15
    assert all(e.endswith("@acme.com") for e in emails)
    assert "purchasing@acme.com" in emails
    assert "engineering@acme.com" in emails
    assert "sales@acme.com" in emails


def test_generate_role_inbox_emails_empty_domain():
    assert generate_role_inbox_emails("") == []
    assert generate_role_inbox_emails(None) == []


def test_role_inbox_category_and_label():
    assert role_inbox_category("purchasing@acme.com") == "procurement"
    assert role_inbox_category("engineering@acme.com") == "engineering"
    assert role_inbox_category("info@acme.com") == "other"
    assert role_inbox_category("unknown@acme.com") == "other"
    assert role_inbox_label("purchasing@acme.com") == "Purchasing"


# ---------------------------------------------------------------------------
# Regression: per-name e-mail association (was global emails[0])
# ---------------------------------------------------------------------------
def test_extract_contacts_associates_email_per_name():
    html = """
    Mike Lee — CEO, mike@acme.com
    Sara Kim — Sales Director, sara@acme.com
    """
    contacts = extract_contacts(html, site_domain="acme.com")
    by_name = {c["name"]: c["email"] for c in contacts}
    assert by_name.get("Mike Lee") == "mike@acme.com"
    assert by_name.get("Sara Kim") == "sara@acme.com"
    # The old bug stamped emails[0] on every contact:
    assert by_name.get("Sara Kim") != "mike@acme.com"


def test_extract_contacts_schema_unchanged():
    contacts = extract_contacts("John Doe — Buyer, john@acme.com", site_domain="acme.com")
    assert contacts
    for c in contacts:
        assert set(c.keys()) == {"name", "title", "email", "linkedin"}


# ---------------------------------------------------------------------------
# Website extraction
# ---------------------------------------------------------------------------
def _website_fetcher():
    home = """
    <html><body>
    <h1>Acme Castings</h1>
    John Smith — Purchasing Manager, john.smith@acme.com
    Jane Doe, Sales Director
    Reach us at sales@acme.com or info@acme.com
    </body></html>
    """
    pages = {
        "https://acme.com": home,
        "https://acme.com/contact": "<html><body>sales@acme.com</body></html>",
    }
    return lambda url: pages.get(url, "")


def test_extract_website_contacts(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()
    seen_emails, seen_names = _seen_sets(db, lead)
    created = svc.extract_website_contacts(
        db,
        lead,
        fetcher=_website_fetcher(),
        seen_emails=seen_emails,
        seen_names=seen_names,
    )
    assert len(created) >= 4

    john = next(c for c in created if c.full_name == "John Smith")
    assert john.email == "john.smith@acme.com"
    assert john.discovery_method == DISCOVERY_METHOD_WEBSITE
    assert john.confidence in (CONFIDENCE_LOW, "medium", CONFIDENCE_HIGH)
    assert john.discovery_score is not None

    jane = next(c for c in created if c.full_name == "Jane Doe")
    assert jane.email is None  # no e-mail on her line

    emails = {c.email for c in created}
    assert "sales@acme.com" in emails
    assert "info@acme.com" in emails


def test_website_contacts_link_email_address(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()
    seen_emails, seen_names = _seen_sets(db, lead)
    created = svc.extract_website_contacts(
        db,
        lead,
        fetcher=_website_fetcher(),
        seen_emails=seen_emails,
        seen_names=seen_names,
    )
    for c in created:
        if c.email:
            assert c.email_address_id is not None


# ---------------------------------------------------------------------------
# PDF extraction (off-domain rejection)
# ---------------------------------------------------------------------------
def _pdf_fetcher_and_extractor():
    pdf_url = "https://acme.com/brochure.pdf"
    home = f'<html><body><a href="{pdf_url}">Brochure</a></body></html>'
    pdf_text = (
        "Tom Ray — Purchasing Manager, tom@acme.com\n"
        "Customer reference: customer@otherco.com\n"
    )

    def fetcher(url):
        if url == "https://acme.com":
            return home
        if url == pdf_url:
            return pdf_text.encode("utf-8")
        return ""

    text_extractor = lambda b: pdf_text
    return fetcher, text_extractor


def test_extract_pdf_contacts_rejects_off_domain(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()
    fetcher, text_extractor = _pdf_fetcher_and_extractor()
    seen_emails, seen_names = _seen_sets(db, lead)
    created = svc.extract_pdf_contacts(
        db,
        lead,
        fetcher=fetcher,
        text_extractor=text_extractor,
        seen_emails=seen_emails,
        seen_names=seen_names,
    )
    emails = {c.email for c in created}
    assert "tom@acme.com" in emails
    # Customer (off-domain) e-mail must be dropped.
    assert "customer@otherco.com" not in emails

    tom = next(c for c in created if c.email == "tom@acme.com")
    assert tom.full_name == "Tom Ray"
    assert tom.discovery_method == "pdf"
    assert tom.source_url.endswith("brochure.pdf")


# ---------------------------------------------------------------------------
# Role-inbox discovery (pattern source)
# ---------------------------------------------------------------------------
def test_generate_email_candidates(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()
    seen_emails, seen_names = _seen_sets(db, lead)
    created = svc.generate_email_candidates(
        db, lead, seen_emails=seen_emails, seen_names=seen_names
    )
    assert len(created) == 15
    for c in created:
        assert c.discovery_method == DISCOVERY_METHOD_PATTERN
        assert c.source == SOURCE_EMAIL_PATTERN
        assert c.email_address_id is not None
        assert c.role  # human label e.g. "Purchasing"
        assert c.title_category in ("procurement", "engineering", "sales", "other")


# ---------------------------------------------------------------------------
# Full orchestration + duplicate prevention + TTL skip
# ---------------------------------------------------------------------------
def test_discover_company_contacts_summary(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()
    summary = svc.discover_company_contacts(
        db, lead, fetcher=_website_fetcher()
    )
    assert set(summary.keys()) >= {"website", "pdf", "role", "total_contacts_created"}
    assert summary["website"]["status"] == DISCOVERY_STATUS_DONE
    assert summary["role"]["status"] == DISCOVERY_STATUS_DONE
    assert summary["total_contacts_created"] > 0


def test_duplicate_prevention_across_runs(db):
    lead = _make_lead(db)
    svc = ContactDiscoveryService()

    seen_emails, seen_names = _seen_sets(db, lead)
    n1 = len(
        svc.extract_website_contacts(
            db, lead, fetcher=_website_fetcher(),
            seen_emails=seen_emails, seen_names=seen_names,
        )
    )
    assert n1 > 0

    # Re-seed from DB (simulating a second run) -> nothing new should be added.
    seen_emails2, seen_names2 = _seen_sets(db, lead)
    n2 = len(
        svc.extract_website_contacts(
            db, lead, fetcher=_website_fetcher(),
            seen_emails=seen_emails2, seen_names=seen_names2,
        )
    )
    assert n2 == 0


def test_ttl_skip_via_discovery_log(db):
    lead = _make_lead(db)
    db.add(
        ContactDiscoveryLog(
            company_id=lead.id,
            domain="acme.com",
            method=DISCOVERY_METHOD_WEBSITE,
            status=DISCOVERY_STATUS_DONE,
        )
    )
    db.commit()

    svc = ContactDiscoveryService()
    # Provide a fetcher that would otherwise create contacts, to prove the
    # engine skips website discovery because a fresh log exists.
    summary = svc.discover_company_contacts(db, lead, fetcher=_website_fetcher())
    assert summary["website"]["status"] == "skipped_ttl"
    # Role inboxes are unaffected (no log for that method) and still run.
    assert summary["role"]["status"] == DISCOVERY_STATUS_DONE
    # No website contacts were created by this run.
    website_contacts = [
        c for c in contacts_crud.list_for_lead(db, lead.id)
        if c.discovery_method == DISCOVERY_METHOD_WEBSITE
    ]
    assert website_contacts == []


# ---------------------------------------------------------------------------
# Schema: three new indexed columns on contacts
# ---------------------------------------------------------------------------
def test_contacts_new_columns_indexed(db):
    insp = inspect(db.bind)
    indexes = insp.get_indexes("contacts")
    cols = {tuple(ix["column_names"]) for ix in indexes}
    assert ("source_url",) in cols
    assert ("discovery_score",) in cols
    assert ("confidence",) in cols
