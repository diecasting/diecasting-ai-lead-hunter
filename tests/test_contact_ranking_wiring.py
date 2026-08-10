"""Phase 14.1.1 — Contact Ranking Pipeline Wiring.

Verifies that the deterministic ``ContactRankingService`` output
(``Contact.ranking_score``) is consumed by the production contact-selection
paths:

  * ``app.outreach.contact_selector`` (pure, reads ranking_score when present)
  * ``app.campaign.service`` (select_contacts consumes ranking_score;
    build_campaign_targets wires the ranking service so the score is produced
    before selection runs)

And that both paths fall back to the pre-14.1 legacy ordering when ranking
data is missing.
"""
from app.campaign import crud as cc_crud, service as svc
from app.models.contact import Contact
from app.models.email_address import EmailAddress
from app.models.lead import CompanyLead
from app.outreach.contact_selector import rank_contacts, select_best_contact


# ---------------------------------------------------------------------------
# Helpers (mirror tests/test_campaign.py)
# ---------------------------------------------------------------------------
def _make_lead(client, website="https://acme.com"):
    r = client.post("/leads", json={"name": "Acme Castings", "website": website})
    assert r.status_code == 201
    return r.json()["id"]


def _set_lead(db, lead_id, **kw):
    lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id).first()
    assert lead is not None
    for k, v in kw.items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead


def _seed_contact(
    db,
    lead_id,
    *,
    name="John Smith",
    first="John",
    email="john.smith@acme.com",
    title="Purchasing Manager",
    category="procurement",
    score=85,
    priority="high",
    seniority="senior",
    email_status="valid",
    do_not_contact=False,
    ranking_score=None,
):
    addr = EmailAddress(
        company_id=lead_id,
        email=email,
        email_type="personal",
        verification_status=email_status,
        verification_score=90,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    contact = Contact(
        lead_id=lead_id,
        full_name=name,
        first_name=first,
        email=email,
        title=title,
        title_category=category,
        seniority=seniority,
        purchasing_score=score,
        priority=priority,
        email_address_id=addr.id,
        do_not_contact=do_not_contact,
        ranking_score=ranking_score,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _make_campaign(client, **kw):
    body = {"name": kw.pop("name", "Spring Push")}
    body.update(kw)
    r = client.post("/api/campaign", json=body)
    assert r.status_code == 200
    return r.json()["id"]


# ---------------------------------------------------------------------------
# outreach.contact_selector — ranking_score consumed when present
# ---------------------------------------------------------------------------
class _RankedContact:
    """Minimal contact-like object carrying a pre-computed ranking_score."""

    def __init__(self, email, role=None, ranking_score=None, primary=False, dnc=False):
        self.email = email
        self.role = role
        self.title = role
        self.ranking_score = ranking_score
        self.is_primary = primary
        self.do_not_contact = dnc
        self.id = id(self)


def test_ranked_purchasing_manager_selected_over_info():
    pm = _RankedContact("pm@acme.com", "Purchasing Manager", ranking_score=90)
    info = _RankedContact("info@acme.com", "Info", ranking_score=20)
    best = select_best_contact([info, pm])
    assert best.email == "pm@acme.com"


def test_ranked_score_dominates_role_priority():
    # An info@ with a far higher ranking_score beats a purchasing manager with a
    # low ranking_score -> the ranking engine output overrides legacy role rank.
    pm = _RankedContact("pm@acme.com", "Purchasing Manager", ranking_score=10)
    info = _RankedContact("info@acme.com", "Info", ranking_score=95)
    best = select_best_contact([pm, info])
    assert best.email == "info@acme.com"


def test_ranked_contact_beats_unranked():
    # A ranked contact (even a low-value role) precedes an unranked one, because
    # "ranking available" always outranks "ranking missing".
    ranked = _RankedContact("x@acme.com", "Intern", ranking_score=50)
    unranked_pm = _RankedContact(
        "pm@acme.com", "Purchasing Manager", ranking_score=None
    )
    best = select_best_contact([unranked_pm, ranked])
    assert best.email == "x@acme.com"


def test_unranked_falls_back_to_role_priority():
    # No ranking data anywhere -> legacy role-priority ordering is used.
    contacts = [
        _RankedContact("eng@acme.com", "Engineering Manager"),
        _RankedContact("pur@acme.com", "Purchasing Manager"),
    ]
    ranked = [c.email for c in rank_contacts(contacts)]
    assert ranked[0] == "pur@acme.com"


# ---------------------------------------------------------------------------
# campaign.service — ranking_score respected by selection
# ---------------------------------------------------------------------------
def test_campaign_selection_respects_ranking_score(client, db):
    lead_id = _make_lead(client)
    # Legacy would rank the procurement contact (purchasing_score=90) first.
    _seed_contact(
        db, lead_id, name="Proc", email="proc@acme.com",
        title="Purchasing Manager", category="procurement", score=90,
        ranking_score=10,
    )
    # Legacy would rank this engineering contact lower (purchasing_score=60),
    # but it carries a higher ranking_score -> must come first.
    _seed_contact(
        db, lead_id, name="Eng", email="eng@acme.com",
        title="Quality Engineer", category="engineering", score=60,
        ranking_score=95,
    )
    ranked = svc.select_contacts(db, lead_id)
    emails = [c.email for c in ranked]
    assert emails[0] == "eng@acme.com"    # ranking_score 95 wins
    assert emails[1] == "proc@acme.com"


def test_campaign_fallback_without_ranking_data(client, db):
    lead_id = _make_lead(client)
    proc = _seed_contact(
        db, lead_id, name="Proc", email="proc@acme.com",
        title="Purchasing Manager", category="procurement", score=90,
        ranking_score=None,
    )
    eng = _seed_contact(
        db, lead_id, name="Eng", email="eng@acme.com",
        title="Quality Engineer", category="engineering", score=60,
        ranking_score=None,
    )
    ranked = svc.select_contacts(db, lead_id)
    emails = [c.email for c in ranked]
    # No ranking data -> legacy procurement-first ordering.
    assert emails[0] == "proc@acme.com"
    assert emails[1] == "eng@acme.com"
    assert proc.ranking_score is None and eng.ranking_score is None


# ---------------------------------------------------------------------------
# campaign.service — build_campaign_targets wires the ranking service
# ---------------------------------------------------------------------------
def test_build_campaign_targets_wires_ranking_service(client, db):
    lead_id = _make_lead(client)
    _set_lead(db, lead_id, industry="Die Casting", country="DE", priority="HIGH")
    _seed_contact(
        db, lead_id, name="Proc", email="proc@acme.com",
        title="Purchasing Manager", category="procurement", score=90,
    )
    _seed_contact(
        db, lead_id, name="Eng", email="eng@acme.com",
        title="Quality Engineer", category="engineering", score=60,
    )
    camp_id = _make_campaign(
        client, name="Wire", target_industry="Die Casting",
        target_country="DE", min_priority="HIGH", daily_limit=100,
    )
    svc.build_campaign_targets(db, svc.get_campaign(db, camp_id))

    # The ranking service was wired: both contacts now carry a ranking_score.
    contacts = db.query(Contact).filter(Contact.lead_id == lead_id).all()
    assert len(contacts) == 2
    assert all(c.ranking_score is not None for c in contacts)

    # The top selected contact (priority_rank == 1) is the highest-ranked one.
    rows = sorted(cc_crud.list_contacts(db, camp_id), key=lambda r: r.priority_rank)
    top = rows[0]
    top_contact = db.query(Contact).filter(Contact.email == top.to_email).first()
    expected_top = max(contacts, key=lambda c: c.ranking_score)
    assert top_contact.email == expected_top.email
