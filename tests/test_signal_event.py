"""Phase 16.1: Intent Event Foundation tests.

Verifies the SignalEvent storage + deterministic dedup/upsert layer:
  1. Signed value range (-100..+100) persists through the ORM.
  2. Dedup/upsert: same dedup key updates in place (no duplicate rows).
  3. Distinct dedup keys produce distinct rows.
  4. Signal value + confidence are clamped to their allowed ranges.
  5. A signal can attach to a CompanyLead, an Opportunity, or a Contact.
  6. TTL: expire_stale() soft-deactivates past-due signals only.
  7. SET NULL cascade: deleting the owning company nulls company_id.
  8. metadata_json round-trips.

Out of scope (not touched here): lead scoring, external APIs, dashboards,
Opportunity scoring logic.
"""
import json
from datetime import datetime, timedelta, timezone

from app.intent.service import SignalEventService, SignalInput
from app.models.contact import Contact
from app.models.lead import CompanyLead
from app.models.opportunity import Opportunity
from app.models.signal_event import SignalEvent


def _now():
    return datetime.now(timezone.utc)


def _company(db, name="Acme"):
    c = CompanyLead(name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _opportunity(db, company):
    o = Opportunity(company_id=company.id, stage="qualification")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _contact(db, company):
    # Contact requires lead_id (CASCADE FK to company_leads).
    c = Contact(lead_id=company.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# 1. Signed value range survives persistence
# ---------------------------------------------------------------------------
def test_model_persists_signed_value_range(db):
    c = _company(db)
    pos = SignalEvent(
        company_id=c.id, source="manual", signal_type="rfq",
        value=75, detected_at=_now(), dedup_key="pos1",
    )
    neg = SignalEvent(
        company_id=c.id, source="manual", signal_type="deterrent",
        value=-80, detected_at=_now(), dedup_key="neg1",
    )
    db.add_all([pos, neg])
    db.commit()
    fetched = {
        s.signal_type: s.value
        for s in db.query(SignalEvent).filter(SignalEvent.id.in_([pos.id, neg.id]))
    }
    assert fetched["rfq"] == 75
    assert fetched["deterrent"] == -80


# ---------------------------------------------------------------------------
# 2. Dedup / upsert: same key -> update in place
# ---------------------------------------------------------------------------
def test_ingest_dedup_updates_in_place(db):
    c = _company(db)
    svc = SignalEventService(db)

    r1 = svc.ingest(
        SignalInput(source="manual", signal_type="rfq", value=50,
                    company_id=c.id, external_id="e1")
    )
    assert r1.created and not r1.updated
    assert r1.signal.id is not None

    r2 = svc.ingest(
        SignalInput(source="manual", signal_type="rfq", value=90,
                    company_id=c.id, external_id="e1")
    )
    assert r2.updated and not r2.created
    assert r2.signal.id == r1.signal.id      # same row
    assert r2.signal.value == 90             # value refreshed
    assert svc.repo.count() == 1             # no duplicate


# ---------------------------------------------------------------------------
# 3. Distinct keys -> distinct rows
# ---------------------------------------------------------------------------
def test_ingest_distinct_keys_create_rows(db):
    c = _company(db)
    svc = SignalEventService(db)
    svc.ingest(SignalInput(source="manual", signal_type="rfq", value=50,
                           company_id=c.id, external_id="e1"))
    svc.ingest(SignalInput(source="manual", signal_type="rfq", value=50,
                           company_id=c.id, external_id="e2"))
    assert svc.repo.count() == 2


# ---------------------------------------------------------------------------
# 4. Clamping of value (signed) and confidence (unsigned)
# ---------------------------------------------------------------------------
def test_value_clamped_to_signed_range(db):
    c = _company(db)
    svc = SignalEventService(db)
    hi = svc.ingest(SignalInput(source="manual", signal_type="hi", value=250,
                                company_id=c.id))
    lo = svc.ingest(SignalInput(source="manual", signal_type="lo", value=-250,
                                company_id=c.id))
    assert hi.signal.value == 100
    assert lo.signal.value == -100


def test_confidence_clamped_to_unsigned_range(db):
    c = _company(db)
    svc = SignalEventService(db)
    over = svc.ingest(SignalInput(source="manual", signal_type="o", value=10,
                                  confidence=999, company_id=c.id))
    under = svc.ingest(SignalInput(source="manual", signal_type="u", value=10,
                                   confidence=-5, company_id=c.id))
    assert over.signal.confidence == 100
    assert under.signal.confidence == 0


# ---------------------------------------------------------------------------
# 5. Entity linkage (company / opportunity / contact)
# ---------------------------------------------------------------------------
def test_entity_linkage_all_three(db):
    c = _company(db)
    o = _opportunity(db, c)
    ct = _contact(db, c)
    svc = SignalEventService(db)

    svc.ingest(SignalInput(source="manual", signal_type="co", value=10,
                           company_id=c.id))
    svc.ingest(SignalInput(source="manual", signal_type="op", value=20,
                           opportunity_id=o.id))
    svc.ingest(SignalInput(source="manual", signal_type="ct", value=-30,
                           contact_id=ct.id))

    assert len(svc.active_for_company(c.id)) == 1
    assert len(svc.active_for_opportunity(o.id)) == 1
    contact_signals = svc.active_for_contact(ct.id)
    assert len(contact_signals) == 1
    assert contact_signals[0].value == -30


# ---------------------------------------------------------------------------
# 6. TTL expiry
# ---------------------------------------------------------------------------
def test_expire_stale_only_past_due(db):
    c = _company(db)
    svc = SignalEventService(db)
    past = _now() - timedelta(days=10)
    future = _now() + timedelta(days=10)

    svc.ingest(SignalInput(source="manual", signal_type="expired", value=10,
                           company_id=c.id, detected_at=past, expires_at=past))
    svc.ingest(SignalInput(source="manual", signal_type="live", value=10,
                           company_id=c.id, detected_at=_now(), expires_at=future))

    flipped = svc.expire_stale(now=_now())
    assert flipped == 1

    active = svc.active_for_company(c.id)
    assert len(active) == 1
    assert active[0].signal_type == "live"


# ---------------------------------------------------------------------------
# 7. SET NULL cascade on owning entity delete
# ---------------------------------------------------------------------------
def test_set_null_on_company_delete(db):
    c = _company(db)
    svc = SignalEventService(db)
    svc.ingest(SignalInput(source="manual", signal_type="x", value=10,
                           company_id=c.id))
    sig = svc.active_for_company(c.id)[0]
    assert sig.company_id == c.id

    db.delete(c)
    db.commit()
    db.refresh(sig)
    assert sig.company_id is None


# ---------------------------------------------------------------------------
# 8. metadata_json round-trip
# ---------------------------------------------------------------------------
def test_metadata_json_stored(db):
    c = _company(db)
    svc = SignalEventService(db)
    r = svc.ingest(
        SignalInput(
            source="manual", signal_type="m", value=5, company_id=c.id,
            metadata={"query": "die casting supplier", "page": "careers"},
        )
    )
    assert r.signal.metadata_json is not None
    parsed = json.loads(r.signal.metadata_json)
    assert parsed["query"] == "die casting supplier"
