"""Phase 15.3.2: Hot Leads API tests.

Verifies ``GET /api/conversion/hot-leads``:
  * returns ranked leads (priority high>medium>low, then temperature desc)
  * label / action / min_temperature filters
  * excludes do_not_contact leads by default; include_suppressed=true includes them
  * empty result

Read-only: the endpoint never recomputes or mutates. Tests seed
:class:`ConversionSignal` rows directly (plus CompanyLead) to control ranking
deterministically without depending on the scoring engine or reply flow.
"""
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead


def _make_lead(db, name, do_not_contact=False):
    lead = CompanyLead(name=name, do_not_contact=do_not_contact)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _signal(db, lead_id, *, priority, temperature, label, action, intent_score=0):
    sig = ConversionSignal(
        lead_id=lead_id,
        intent_score=intent_score,
        dominant_intent="rfq_request" if action == "prepare_quote" else "interested",
        temperature_score=temperature,
        temperature_label=label,
        next_action=action,
        next_action_priority=priority,
        next_action_reason="test seed",
    )
    db.add(sig)
    db.commit()
    return sig


# ---------------------------------------------------------------------------
# 1. Returns ranked leads
# ---------------------------------------------------------------------------
def test_hot_leads_returns_leads(db, client):
    l1 = _make_lead(db, "HotA")
    l2 = _make_lead(db, "WarmB")
    _signal(db, l1.id, priority="high", temperature=80, label="hot", action="prepare_quote")
    _signal(db, l2.id, priority="medium", temperature=50, label="warm", action="send_capability_case")

    r = client.get("/api/conversion/hot-leads")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert {b["lead_id"] for b in body} == {l1.id, l2.id}
    # company_name surfaced from the join
    assert {b["company_name"] for b in body} == {"HotA", "WarmB"}


# ---------------------------------------------------------------------------
# 2. Priority ordering (high > medium > low)
# ---------------------------------------------------------------------------
def test_hot_leads_priority_ordering(db, client):
    hi = _make_lead(db, "Hi")
    med = _make_lead(db, "Med")
    lo = _make_lead(db, "Lo")
    # Same temperature, different priority.
    _signal(db, hi.id, priority="high", temperature=40, label="warm", action="prepare_quote")
    _signal(db, med.id, priority="medium", temperature=40, label="warm", action="send_capability_case")
    _signal(db, lo.id, priority="low", temperature=40, label="warm", action="send_capability_case")

    r = client.get("/api/conversion/hot-leads")
    assert r.status_code == 200
    ids = [b["lead_id"] for b in r.json()]
    assert ids == [hi.id, med.id, lo.id]


# ---------------------------------------------------------------------------
# 3. Temperature ordering (desc) within same priority
# ---------------------------------------------------------------------------
def test_hot_leads_temperature_ordering(db, client):
    a = _make_lead(db, "TA")
    b = _make_lead(db, "TB")
    c = _make_lead(db, "TC")
    _signal(db, a.id, priority="high", temperature=30, label="cold", action="prepare_quote")
    _signal(db, b.id, priority="high", temperature=90, label="hot", action="prepare_quote")
    _signal(db, c.id, priority="high", temperature=60, label="warm", action="prepare_quote")

    r = client.get("/api/conversion/hot-leads")
    assert r.status_code == 200
    ids = [b["lead_id"] for b in r.json()]
    assert ids == [b.id, c.id, a.id]  # 90, 60, 30


# ---------------------------------------------------------------------------
# 4. Label filter
# ---------------------------------------------------------------------------
def test_hot_leads_label_filter(db, client):
    hot = _make_lead(db, "H")
    warm = _make_lead(db, "W")
    _signal(db, hot.id, priority="high", temperature=80, label="hot", action="prepare_quote")
    _signal(db, warm.id, priority="high", temperature=50, label="warm", action="send_capability_case")

    r = client.get("/api/conversion/hot-leads?label=hot")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["lead_id"] == hot.id
    assert body[0]["temperature_label"] == "hot"


# ---------------------------------------------------------------------------
# 5. Action filter
# ---------------------------------------------------------------------------
def test_hot_leads_action_filter(db, client):
    pq = _make_lead(db, "PQ")
    sc = _make_lead(db, "SC")
    _signal(db, pq.id, priority="high", temperature=80, label="hot", action="prepare_quote")
    _signal(db, sc.id, priority="high", temperature=80, label="hot", action="send_capability_case")

    r = client.get("/api/conversion/hot-leads?action=prepare_quote")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["lead_id"] == pq.id
    assert body[0]["next_action"] == "prepare_quote"


# ---------------------------------------------------------------------------
# 6. Minimum temperature filter
# ---------------------------------------------------------------------------
def test_hot_leads_min_temperature_filter(db, client):
    hi_t = _make_lead(db, "HiT")
    lo_t = _make_lead(db, "LoT")
    _signal(db, hi_t.id, priority="high", temperature=75, label="hot", action="prepare_quote")
    _signal(db, lo_t.id, priority="high", temperature=20, label="cold", action="prepare_quote")

    r = client.get("/api/conversion/hot-leads?min_temperature=70")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["lead_id"] == hi_t.id
    assert body[0]["temperature_score"] >= 70


# ---------------------------------------------------------------------------
# 7. Excludes do_not_contact leads by default
# ---------------------------------------------------------------------------
def test_hot_leads_excludes_do_not_contact(db, client):
    ok = _make_lead(db, "Ok")
    dnc = _make_lead(db, "Dnc", do_not_contact=True)
    _signal(db, ok.id, priority="high", temperature=80, label="hot", action="prepare_quote")
    _signal(db, dnc.id, priority="high", temperature=90, label="hot", action="prepare_quote")

    r = client.get("/api/conversion/hot-leads")
    assert r.status_code == 200
    body = r.json()
    lead_ids = {b["lead_id"] for b in body}
    assert ok.id in lead_ids
    assert dnc.id not in lead_ids


# ---------------------------------------------------------------------------
# 8. include_suppressed=true includes do_not_contact leads
# ---------------------------------------------------------------------------
def test_hot_leads_include_suppressed(db, client):
    dnc = _make_lead(db, "Dnc", do_not_contact=True)
    _signal(db, dnc.id, priority="high", temperature=90, label="hot", action="prepare_quote")

    excluded = client.get("/api/conversion/hot-leads")
    assert dnc.id not in {b["lead_id"] for b in excluded.json()}

    included = client.get("/api/conversion/hot-leads?include_suppressed=true")
    assert included.status_code == 200
    body = included.json()
    assert len(body) == 1
    assert body[0]["lead_id"] == dnc.id


# ---------------------------------------------------------------------------
# 9. Empty result
# ---------------------------------------------------------------------------
def test_hot_leads_empty(db, client):
    r = client.get("/api/conversion/hot-leads")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# 10. limit caps the result set
# ---------------------------------------------------------------------------
def test_hot_leads_limit(db, client):
    for i in range(5):
        l = _make_lead(db, f"L{i}")
        _signal(
            db, l.id, priority="high", temperature=50 + i, label="warm",
            action="prepare_quote",
        )

    r = client.get("/api/conversion/hot-leads?limit=3")
    assert r.status_code == 200
    assert len(r.json()) == 3
