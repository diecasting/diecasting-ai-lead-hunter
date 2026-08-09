"""Phase 13.2.1 — Contact Discovery Pipeline Wiring tests.

Verifies that ``discovery_to_lead`` triggers the Contact Discovery Engine after
a ``CompanyLead`` is created, and that a discovery failure never blocks lead
creation. All tests are offline (no network): the discovery engine runs with an
injected fetcher or with no fetcher (role-inbox generation is pure).
"""
import logging

from app.crud import contacts as contacts_crud
from app.crud import leads as leads_crud
from app.discovery.qualify import discovery_to_lead
from app.models.company_discovery import CompanyDiscovery


def _make_discovery(db, *, website: str, company_name: str = "Acme Co", lead_score: int = 60):
    disc = CompanyDiscovery(
        company_name=company_name,
        website=website,
        lead_score=lead_score,
        detected_processes="die casting",
        buying_signals="rfq",
    )
    db.add(disc)
    db.commit()
    db.refresh(disc)
    return disc


def _contact_fetcher(url: str) -> str:
    """Return a page whose only content is one named, on-domain contact."""
    return (
        "<html><body>"
        "Jane Doe - Purchasing Manager, jane@acme-castings.example.com"
        "</body></html>"
    )


def test_discovery_to_lead_triggers_contact_discovery(db, caplog):
    caplog.set_level(logging.INFO, logger="app.discovery.qualify")
    disc = _make_discovery(db, website="https://acme-castings.example.com")

    lead, status = discovery_to_lead(
        db, disc, contact_discovery_fetcher=_contact_fetcher
    )

    # Lead creation succeeded and is linked.
    assert status == "created"
    assert lead.id is not None
    assert lead.website == "https://acme-castings.example.com"

    # Contact discovery ran: website source produced the named contact.
    contacts = contacts_crud.list_for_lead(db, lead.id)
    emails = {c.email for c in contacts}
    assert "jane@acme-castings.example.com" in emails
    # Pattern source produced role inboxes (they carry a role label).
    assert any(c.role for c in contacts)

    # Structured log was emitted for the completed run.
    assert any(
        r.message == "contact_discovery_completed" and getattr(r, "lead_id", None) == lead.id
        for r in caplog.records
    )


def test_discovery_to_lead_without_fetcher_creates_role_inboxes(db):
    """Production-like path: no fetcher => no crawl, but role inboxes appear."""
    disc = _make_discovery(db, website="https://roleco.example.com")

    lead, status = discovery_to_lead(db, disc)

    assert status == "created"
    contacts = contacts_crud.list_for_lead(db, lead.id)
    # No fetcher -> website/PDF find nothing; only role inboxes are generated.
    assert any(c.role for c in contacts)
    assert any(c.email.endswith("@roleco.example.com") for c in contacts)


def test_discovery_failure_does_not_fail_lead_creation(db, monkeypatch):
    disc = _make_discovery(db, website="https://failco.example.com")

    def _boom(self, db, company, **kwargs):
        raise RuntimeError("discovery boom")

    monkeypatch.setattr(
        "app.contact_discovery.service.ContactDiscoveryService.discover_company_contacts",
        _boom,
    )

    # Lead creation must still succeed even though discovery raises.
    lead, status = discovery_to_lead(db, disc)
    assert status == "created"
    assert lead is not None

    # The lead is durable (committed before discovery ran).
    assert leads_crud.get(db, lead.id) is not None
