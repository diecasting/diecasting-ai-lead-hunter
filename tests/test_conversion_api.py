"""Phase 15.3.1: Conversion Read API tests.

Verifies the read-only ``GET /api/conversion/lead/{lead_id}`` endpoint:
  * an existing ConversionSignal returns 200 with the full snapshot
  * a lead with no signal returns 404
  * a non-existent lead returns 404

No SalesTask, no accept endpoint, no mutations. All tests are offline
(``db`` / ``client`` fixtures from conftest.py).
"""
import pytest

from app.conversion.service import ConversionService
from app.models.conversion_signal import ConversionSignal
from app.models.lead import CompanyLead


def _make_lead(db, name):
    lead = CompanyLead(name=name)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Existing signal -> 200 with full snapshot
# ---------------------------------------------------------------------------
def test_get_conversion_signal_returns_200(db, client):
    lead = _make_lead(db, "ConvReadOk")

    # Populate a deterministic snapshot without touching the reply flow.
    ConversionService(db).recompute(lead.id)

    r = client.get(f"/api/conversion/lead/{lead.id}")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["lead_id"] == lead.id
    # Engine outputs are present (values may be None for a lead with no replies,
    # but the keys must exist and be serializable).
    for key in (
        "intent_score",
        "dominant_intent",
        "signal_sources",
        "temperature_score",
        "temperature_label",
        "next_action",
        "next_action_priority",
        "next_action_reason",
        "computed_at",
    ):
        assert key in body, f"missing key {key}"

    # signal_sources is a parsed dict (or None) — never a raw JSON string.
    assert body["signal_sources"] is None or isinstance(body["signal_sources"], dict)
    # computed_at is an ISO string when present.
    if body["computed_at"] is not None:
        assert isinstance(body["computed_at"], str)


# ---------------------------------------------------------------------------
# Missing signal -> 404
# ---------------------------------------------------------------------------
def test_get_conversion_signal_missing_signal_404(db, client):
    lead = _make_lead(db, "ConvNoSignal")
    # Lead exists but no ConversionSignal row has been computed.

    r = client.get(f"/api/conversion/lead/{lead.id}")
    assert r.status_code == 404, r.text
    assert "Conversion signal not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Missing lead -> 404
# ---------------------------------------------------------------------------
def test_get_conversion_signal_missing_lead_404(db, client):
    # Use an id that cannot exist.
    r = client.get("/api/conversion/lead/999999999")
    assert r.status_code == 404, r.text
    assert "Lead not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Endpoint is truly read-only (no signal row created by a GET)
# ---------------------------------------------------------------------------
def test_get_conversion_signal_does_not_create_row(db, client):
    lead = _make_lead(db, "ConvReadOnly")

    before = (
        db.query(ConversionSignal)
        .filter_by(lead_id=lead.id)
        .count()
    )
    assert before == 0

    r = client.get(f"/api/conversion/lead/{lead.id}")
    assert r.status_code == 404  # confirms read-only: no row synthesized

    after = (
        db.query(ConversionSignal)
        .filter_by(lead_id=lead.id)
        .count()
    )
    assert after == 0
