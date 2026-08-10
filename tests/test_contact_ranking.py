"""Phase 14.1 — Contact Ranking Engine.

Deterministic, offline (no network, no LLM) coverage of the ranking rules and
service:

  * role/title, e-mail type, verification and manufacturing components
  * a purchasing manager outranks a generic role mailbox (info@)
  * a verified personal address outranks a role mailbox
  * a manufacturing-relevant title scores higher than a non-relevant one
  * deterministic output
  * rank_company_contacts returns contacts sorted by score
  * the three new indexed ``contacts`` columns exist
"""
from sqlalchemy import inspect

from app.contact_ranking.rules import (
    email_type_score,
    manufacturing_relevance_score,
    role_title_score,
    verification_score,
)
from app.contact_ranking.scorer import compute_ranking
from app.contact_ranking.service import ContactRankingService
from app.crud import contacts as contacts_crud
from app.models.contact import Contact
from app.models.email_address import (
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VALID,
    EmailAddress,
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


def _make_email(db, lead, email, email_type, status):
    row = EmailAddress(
        company_id=lead.id,
        email=email,
        email_type=email_type,
        verification_status=status,
        verification_score=95 if status == VERIFICATION_VALID else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_contact(db, lead, **kwargs):
    obj = Contact(lead_id=lead.id, **kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ---------------------------------------------------------------------------
# Rule unit tests (pure functions)
# ---------------------------------------------------------------------------
def test_role_title_score_procurement_manager_high():
    # "Purchasing Manager" -> procurement (25) + senior (12) = 37
    assert role_title_score("Purchasing Manager", None) == 37
    # An executive (CEO) -> executive (22) + executive seniority (15) = 37
    assert role_title_score("CEO", None) == 37


def test_role_title_score_role_mailbox_low():
    # info@ has no meaningful title -> other (5) + mid (8) = 13
    assert role_title_score(None, "General") == 13
    assert role_title_score("Receptionist", None) == 13  # other(5)+mid(8)


def test_email_type_score_ordering():
    assert email_type_score("john.smith@acme.com") == 25  # personal
    assert email_type_score("sales@acme.com") == 8  # role
    assert email_type_score(None) == 0  # none


def test_verification_score_ordering():
    assert verification_score(VERIFICATION_VALID) == 25
    assert verification_score("risky") == 12
    assert verification_score(VERIFICATION_UNVERIFIED) == 5
    assert verification_score("invalid") == 0
    assert verification_score(None) == 0


def test_manufacturing_relevance_keywords():
    # Keyword path (category would be "other" but title carries CNC/machinist).
    assert manufacturing_relevance_score(title="CNC Machinist") == 10
    # Category path.
    assert manufacturing_relevance_score(title_category="procurement") == 10
    assert manufacturing_relevance_score(title_category="engineering") == 10
    # Non-manufacturing.
    assert manufacturing_relevance_score(title="Receptionist") == 0
    assert manufacturing_relevance_score(title_category="other") == 0


# ---------------------------------------------------------------------------
# Required behaviour: purchasing manager ranks above info@
# ---------------------------------------------------------------------------
def test_purchasing_manager_ranks_above_info_mailbox(db):
    lead = _make_lead(db)

    pm_email = _make_email(
        db, lead, "jane.buyer@acme.com", "personal", VERIFICATION_VALID
    )
    _make_contact(
        db, lead,
        full_name="Jane Buyer", title="Purchasing Manager",
        email="jane.buyer@acme.com", email_address_id=pm_email.id,
    )

    info_email = _make_email(
        db, lead, "info@acme.com", "role", VERIFICATION_UNVERIFIED
    )
    _make_contact(
        db, lead,
        full_name="General", role="General",
        email="info@acme.com", email_address_id=info_email.id,
    )

    svc = ContactRankingService(db)
    ranked = svc.rank_company_contacts(lead.id)
    scores = {c.email: c.ranking_score for c in ranked}

    assert scores["jane.buyer@acme.com"] > scores["info@acme.com"]
    # Sanity: the purchasing manager is the top contact.
    assert ranked[0].email == "jane.buyer@acme.com"


# ---------------------------------------------------------------------------
# Required behaviour: verified personal email ranks above role mailbox
# ---------------------------------------------------------------------------
def test_verified_personal_ranks_above_role_mailbox(db):
    lead = _make_lead(db)

    personal_email = _make_email(
        db, lead, "john@acme.com", "personal", VERIFICATION_VALID
    )
    _make_contact(
        db, lead,
        full_name="John Doe", email="john@acme.com",
        email_address_id=personal_email.id,
    )

    role_email = _make_email(
        db, lead, "info@acme.com", "role", VERIFICATION_UNVERIFIED
    )
    _make_contact(
        db, lead,
        full_name="General", email="info@acme.com",
        email_address_id=role_email.id,
    )

    svc = ContactRankingService(db)
    ranked = svc.rank_company_contacts(lead.id)
    scores = {c.email: c.ranking_score for c in ranked}

    assert scores["john@acme.com"] > scores["info@acme.com"]


# ---------------------------------------------------------------------------
# Required behaviour: manufacturing-relevant title increases score
# ---------------------------------------------------------------------------
def test_manufacturing_relevant_title_increases_score(db):
    lead = _make_lead(db)

    # Same e-mail type (generic) + same verification for both, only the title
    # differs — so any score gap must come from the manufacturing component.
    machinist_email = _make_email(
        db, lead, "a.machinist@acme.com", "generic", VERIFICATION_UNVERIFIED
    )
    _make_contact(
        db, lead,
        full_name="A Machinist", title="CNC Machinist",
        email="a.machinist@acme.com", email_address_id=machinist_email.id,
    )

    reception_email = _make_email(
        db, lead, "b.reception@acme.com", "generic", VERIFICATION_UNVERIFIED
    )
    _make_contact(
        db, lead,
        full_name="B Reception", title="Receptionist",
        email="b.reception@acme.com", email_address_id=reception_email.id,
    )

    svc = ContactRankingService(db)
    ranked = svc.rank_company_contacts(lead.id)
    scores = {c.email: c.ranking_score for c in ranked}

    assert scores["a.machinist@acme.com"] > scores["b.reception@acme.com"]


# ---------------------------------------------------------------------------
# Required behaviour: deterministic output
# ---------------------------------------------------------------------------
def test_ranking_is_deterministic():
    class _FakeContact:
        title = "Purchasing Manager"
        role = None
        email = "jane.buyer@acme.com"
        title_category = "procurement"

    class _FakeEmail:
        verification_status = VERIFICATION_VALID

    r1 = compute_ranking(_FakeContact(), email_address=_FakeEmail())
    r2 = compute_ranking(_FakeContact(), email_address=_FakeEmail())
    assert r1.score == r2.score
    assert r1.confidence == r2.confidence
    assert r1.reason == r2.reason


# ---------------------------------------------------------------------------
# Service: single contact persist + schema columns
# ---------------------------------------------------------------------------
def test_rank_contact_persists_fields(db):
    lead = _make_lead(db)
    email = _make_email(
        db, lead, "jane.buyer@acme.com", "personal", VERIFICATION_VALID
    )
    contact = _make_contact(
        db, lead,
        full_name="Jane Buyer", title="Purchasing Manager",
        email="jane.buyer@acme.com", email_address_id=email.id,
    )

    svc = ContactRankingService(db)
    updated = svc.rank_contact(contact)

    assert updated.ranking_score is not None
    assert updated.ranking_confidence in ("high", "medium", "low")
    assert "score=" in (updated.ranking_reason or "")

    # Re-read from DB to prove it was persisted.
    refreshed = contacts_crud.get(db, contact.id)
    assert refreshed.ranking_score == updated.ranking_score
    assert refreshed.ranking_confidence == updated.ranking_confidence

    # Discovery fields must be untouched.
    assert refreshed.discovery_score is None
    assert refreshed.confidence is None


def test_rank_company_contacts_returns_sorted(db):
    lead = _make_lead(db)

    pm = _make_email(db, lead, "jane@acme.com", "personal", VERIFICATION_VALID)
    _make_contact(
        db, lead, full_name="Jane", title="Purchasing Manager",
        email="jane@acme.com", email_address_id=pm.id,
    )
    role = _make_email(db, lead, "info@acme.com", "role", VERIFICATION_UNVERIFIED)
    _make_contact(
        db, lead, full_name="General", email="info@acme.com",
        email_address_id=role.id,
    )

    svc = ContactRankingService(db)
    ranked = svc.rank_company_contacts(lead.id)

    scores = [c.ranking_score for c in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].email == "jane@acme.com"


# ---------------------------------------------------------------------------
# Schema: three new indexed columns on contacts
# ---------------------------------------------------------------------------
def test_contacts_ranking_columns_indexed(db):
    insp = inspect(db.bind)
    indexes = insp.get_indexes("contacts")
    cols = {tuple(ix["column_names"]) for ix in indexes}
    assert ("ranking_score",) in cols
    assert ("ranking_confidence",) in cols
