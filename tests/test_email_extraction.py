"""Unit tests for app.crawler.email_extractor (no browser required)."""
from app.crawler.email_extractor import (
    extract_and_filter,
    extract_emails,
    filter_emails,
)


def test_extract_emails_finds_standard_addresses():
    text = "Reach us at sales@acme.com or info@acme.com, invalid foo@bar"
    found = extract_emails(text)
    assert "sales@acme.com" in found
    assert "info@acme.com" in found
    assert "foo@bar" not in found  # no TLD


def test_filter_removes_noise_domains_and_mailboxes():
    emails = {
        "sales@acme.com",
        "noreply@acme.com",
        "support@acme.com",
        "privacy@acme.com",
        "test@test.com",
        "demo@example.com",
        "ceo@gmail.com",
    }
    kept = filter_emails(emails)
    assert "sales@acme.com" in kept
    assert "noreply@acme.com" not in kept
    assert "support@acme.com" not in kept
    assert "privacy@acme.com" not in kept
    assert "test@test.com" not in kept
    assert "demo@example.com" not in kept
    assert "ceo@gmail.com" not in kept  # free provider dropped


def test_filter_prioritises_sales_intent_mailboxes():
    emails = {
        "info@acme.com",
        "sales@acme.com",
        "contact@acme.com",
        "inquiry@acme.com",
        "export@acme.com",
        "business@acme.com",
    }
    ranked = filter_emails(emails)
    # sales must be first; order follows PRIORITY_LOCAL.
    assert ranked[0] == "sales@acme.com"
    assert ranked.index("export@acme.com") < ranked.index("info@acme.com")


def test_filter_prefers_on_domain_addresses():
    emails = {"sales@other-partner.com", "info@acme.com", "contact@acme.com"}
    ranked = filter_emails(emails, site_domain="acme.com")
    # on-domain addresses come before the off-domain one
    assert ranked[-1] == "sales@other-partner.com"
    assert "acme.com" in ranked[0]


def test_extract_and_filter_end_to_end():
    html = "Contact sales@acme.com or noreply@acme.com for support@acme.com help."
    out = extract_and_filter(html, site_domain="acme.com")
    assert out == ["sales@acme.com"]
