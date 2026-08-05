"""Tests for the email draft quality auto-gate (Phase 4 Stage 3).

Covers:
  * classify_quality_gate boundary mapping (None / ready / review / blocked)
  * gate_allows_send policy
  * evaluate_message recompute path for legacy (unscored) drafts
  * list_drafts ``gate`` filter + PATCH /outreach/drafts/{id}/gate override
  * generate-email wiring stores a derived gate status (offline, mocked LLM)
"""
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.crud import leads as leads_crud
from app.crud import outreach as outreach_crud
from app.outreach.draft_quality_gate import (
    GATE_BLOCKED,
    GATE_READY,
    GATE_REVIEW,
    classify_quality_gate,
    evaluate_message,
    gate_allows_send,
)


# ---------------------------------------------------------------------------
# Pure classification logic
# ---------------------------------------------------------------------------
def test_classify_quality_gate_boundaries():
    assert classify_quality_gate(None) is None
    assert classify_quality_gate(100) == GATE_READY
    assert classify_quality_gate(70) == GATE_READY  # exactly on threshold
    assert classify_quality_gate(69) == GATE_REVIEW
    assert classify_quality_gate(40) == GATE_REVIEW  # exactly on threshold
    assert classify_quality_gate(39) == GATE_BLOCKED
    assert classify_quality_gate(0) == GATE_BLOCKED


def test_classify_quality_gate_custom_thresholds():
    assert classify_quality_gate(50, ready_threshold=80, block_threshold=30) == GATE_REVIEW
    assert classify_quality_gate(50, ready_threshold=40, block_threshold=20) == GATE_READY
    assert classify_quality_gate(None, ready_threshold=80) is None


def test_gate_allows_send_policy():
    assert gate_allows_send(GATE_READY) is True
    assert gate_allows_send(GATE_REVIEW) is False
    assert gate_allows_send(GATE_BLOCKED) is False
    assert gate_allows_send(None) is False


class _Msg:
    """Minimal duck-typed stand-in for OutreachMessage."""

    def __init__(self, body: str = "", quality_score: Optional[int] = None):
        self.body = body
        self.quality_score = quality_score


def test_evaluate_message_uses_stored_score():
    decision = evaluate_message(_Msg(body="ignored", quality_score=85))
    assert decision.status == GATE_READY
    assert decision.can_send is True


def test_evaluate_message_recomputes_unscored_draft():
    body = (
        "Hi Acme Castings, we noticed you manufacture aluminium high pressure "
        "die castings for the automotive sector. Our tooling solutions reduce "
        "cycle time and scrap. Could we schedule a call to discuss your "
        "procurement needs for the new EV program?"
    )
    decision = evaluate_message(_Msg(body=body, quality_score=None))
    assert decision.status in (GATE_READY, GATE_REVIEW, GATE_BLOCKED)
    assert decision.can_send == (decision.status == GATE_READY)


def test_evaluate_message_unscored_no_body_is_blocked():
    decision = evaluate_message(_Msg(body="", quality_score=None))
    assert decision.status is None
    assert decision.can_send is False


# ---------------------------------------------------------------------------
# API: filter + reviewer override
# ---------------------------------------------------------------------------
def _make_lead(db):
    return leads_crud.create(db, name="Gate Test Co", lead_status="new")


def _insert_draft(db, lead_id, quality_score, gate_status):
    return outreach_crud.create(
        db,
        lead_id=lead_id,
        subject=f"Draft q={quality_score}",
        body="Body text for the draft.",
        quality_score=quality_score,
        quality_gate_status=gate_status,
    )


def test_drafts_gate_filter_and_override(client: TestClient, db):
    lead = _make_lead(db)
    ready = _insert_draft(db, lead.id, 85, GATE_READY)
    review = _insert_draft(db, lead.id, 55, GATE_REVIEW)
    blocked = _insert_draft(db, lead.id, 20, GATE_BLOCKED)
    unscored = _insert_draft(db, lead.id, None, None)

    # No filter -> all four drafts.
    all_drafts = client.get("/outreach/drafts").json()
    assert {d["id"] for d in all_drafts} == {ready.id, review.id, blocked.id, unscored.id}

    # Filter by each gate status.
    for status, obj in ((GATE_READY, ready), (GATE_REVIEW, review), (GATE_BLOCKED, blocked)):
        resp = client.get(f"/outreach/drafts?gate={status}").json()
        assert [d["id"] for d in resp] == [obj.id]
        assert resp[0]["quality_gate_status"] == status

    # Invalid gate value is rejected by the schema.
    bad = client.get("/outreach/drafts?gate=bogus")
    assert bad.status_code == 422

    # Reviewer releases a blocked draft -> becomes ready.
    patch = client.patch(
        f"/outreach/drafts/{blocked.id}/gate", json={"gate_status": GATE_READY}
    )
    assert patch.status_code == 200
    assert patch.json()["quality_gate_status"] == GATE_READY

    after = client.get(f"/outreach/drafts?gate={GATE_READY}").json()
    assert {d["id"] for d in after} == {ready.id, blocked.id}

    # Unknown draft id -> 404.
    assert client.patch("/outreach/drafts/999999/gate", json={"gate_status": GATE_READY}).status_code == 404

    # Invalid override payload -> 422.
    assert client.patch(f"/outreach/drafts/{review.id}/gate", json={"gate_status": "nope"}).status_code == 422


def test_generate_email_stores_gate_status(client: TestClient, db, monkeypatch):
    """generate-email must derive and persist a quality_gate_status (offline)."""
    from app.outreach.draft_quality_gate import classify_quality_gate

    def fake_generate(db, lead, use_llm=True):
        return {
            "subject": "Partnership opportunity",
            "opening": "Hi",
            "body": "We help aluminium die casters in automotive reduce scrap.",
            "call_to_action": "Can we schedule a call?",
            "contact_role": "Purchasing Manager",
        }

    monkeypatch.setattr(
        "app.routers.leads.generate_email_from_lead", fake_generate
    )

    lead = _make_lead(db)
    resp = client.post(f"/leads/{lead.id}/generate-email")
    assert resp.status_code in (200, 201), resp.text
    msg = resp.json()
    assert msg["quality_score"] is not None
    assert msg["quality_gate_status"] == classify_quality_gate(msg["quality_score"])
