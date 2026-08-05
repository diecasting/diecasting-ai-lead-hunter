"""Phase 6.5 — Lead e-mail verification (MX / syntax / SMTP).

Covers:
  * the ``verify_lead_email`` verifier with injected MX resolver + SMTP probe:
      - bad syntax                        -> invalid, score 0
      - definitive "no MX" (resolver [])  -> invalid (requirement 4: blocks send)
      - lookup inconclusive (resolver None) -> unknown (does NOT block)
      - MX ok + SMTP deliverable          -> valid
      - MX ok + SMTP undeliverable        -> invalid
      - MX ok + SMTP unknown              -> unknown
      - disposable provider               -> soft downgrade to unknown
  * the POST /outreach/leads/{id}/verify-email endpoint stores the result on the
    lead (email_status + email_confidence_score) and returns the checks.
  * the send pipeline blocks (422) when verification is invalid (no MX).
"""
from fastapi.testclient import TestClient

from app.outreach.email_verifier import INVALID, UNKNOWN, VALID, VerificationResult
from app.outreach.lead_email_verifier import verify_lead_email


# ---------------------------------------------------------------------------
# Verifier unit tests (no network — inject fakes)
# ---------------------------------------------------------------------------
def test_syntax_invalid_is_invalid():
    r = verify_lead_email("not-an-email")
    assert r.status == INVALID
    assert r.score == 0


def test_definitive_no_mx_is_invalid():
    r = verify_lead_email(
        "buyer@nodomain.example", mx_resolver=lambda d: []
    )
    assert r.status == INVALID
    assert "no MX" in r.reason
    # confirm the send path would block on this
    assert r.is_blocked()


def test_inconclusive_mx_is_unknown_not_invalid():
    r = verify_lead_email(
        "buyer@unknown.example", mx_resolver=lambda d: None
    )
    assert r.status == UNKNOWN
    assert not r.is_blocked()  # inconclusive must NOT block a send


def test_mx_ok_smtp_deliverable_is_valid():
    r = verify_lead_email(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "deliverable",
    )
    assert r.status == VALID
    assert r.score == 95


def test_mx_ok_smtp_undeliverable_is_invalid():
    r = verify_lead_email(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "undeliverable",
    )
    assert r.status == INVALID


def test_mx_ok_smtp_unknown_is_unknown():
    r = verify_lead_email(
        "buyer@ok.com",
        mx_resolver=lambda d: ["mx.ok.com"],
        smtp_check=lambda h, e: "unknown",
    )
    assert r.status == UNKNOWN
    assert r.score == 60
    # detail["checks"] must be a list of per-verifier dicts (for the API/UI).
    assert isinstance(r.detail["checks"], list)
    assert all("verifier" in c for c in r.detail["checks"])


def test_disposable_downgrades_softly():
    r = verify_lead_email(
        "info@mailinator.com",
        mx_resolver=lambda d: ["mx.mailinator.com"],
        smtp_check=lambda h, e: "unknown",
    )
    assert r.status == UNKNOWN
    assert r.score <= 30


# ---------------------------------------------------------------------------
# Endpoint + send-blocking integration
# ---------------------------------------------------------------------------
def _make_lead(client: TestClient, contact_email: str) -> int:
    r = client.post(
        "/leads",
        json={
            "name": f"Verify {contact_email}",
            "website": f"https://verify-{abs(hash(contact_email))}.example.com",
            "industry": "automotive",
            "contact_role": "Purchasing Manager",
            "contact_email": contact_email,
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_verify_endpoint_stores_result(client: TestClient, monkeypatch):
    import app.outreach.lead_email_verifier as lev_mod

    lead_id = _make_lead(client, "buyer@good.com")
    monkeypatch.setattr(
        lev_mod,
        "verify_lead_email",
        lambda email, **kw: VerificationResult(
            status=VALID,
            verifier="lead_email",
            score=92,
            reason="domain good.com has 1 MX record(s)",
            detail={
                "checks": [
                    {"verifier": "syntax", "status": "valid", "reason": "syntax OK"},
                    {
                        "verifier": "mx",
                        "status": "valid",
                        "mx_records": ["mx.good.com"],
                        "reason": "domain good.com has 1 MX record(s)",
                    },
                    {
                        "verifier": "smtp",
                        "status": "deliverable",
                        "mx_host": "mx.good.com",
                        "reason": "SMTP probe via mx.good.com: deliverable",
                    },
                ]
            },
        ),
    )

    r = client.post(f"/outreach/leads/{lead_id}/verify-email")
    assert r.status_code == 200
    body = r.json()
    assert body["email_status"] == "valid"
    # Confidence blends the verifier score with the contact role (0-100).
    assert 0 <= (body["email_confidence_score"] or 0) <= 100
    assert body["email"] == "buyer@good.com"
    assert any(c["verifier"] == "mx" for c in body["checks"])

    # Persisted on the lead row and consistent with the response.
    lead = client.get(f"/leads/{lead_id}").json()
    assert lead["email_status"] == "valid"
    assert lead["email_confidence_score"] == body["email_confidence_score"]


def test_verify_endpoint_requires_email(client: TestClient):
    r = client.post("/leads", json={"name": "NoMail", "website": "https://nomail.example.com"})
    lead_id = r.json()["id"]
    res = client.post(f"/outreach/leads/{lead_id}/verify-email")
    assert res.status_code == 422
    assert "no contact_email" in res.json()["detail"]


def test_send_blocked_when_verification_invalid(client: TestClient, monkeypatch):
    import app.outreach.lead_email_verifier as lev_mod

    lead_id = _make_lead(client, "buyer@nomx.com")
    # Generate + release a draft.
    gen = client.post(f"/leads/{lead_id}/generate-email")
    assert gen.status_code == 201
    msg_id = gen.json()["id"]
    g = client.patch(
        f"/outreach/drafts/{msg_id}/gate", json={"gate_status": "ready"}
    )
    assert g.status_code == 200

    # Force the pre-send verification to report "no MX" (invalid).
    monkeypatch.setattr(
        lev_mod,
        "verify_lead_email",
        lambda email, **kw: VerificationResult(
            status=INVALID,
            verifier="lead_email",
            score=15,
            reason="domain nomx.com has no MX records",
            detail={"checks": []},
        ),
    )

    r = client.post(f"/outreach/drafts/{msg_id}/send")
    assert r.status_code == 422
    assert "email verification blocked" in r.json()["detail"]
