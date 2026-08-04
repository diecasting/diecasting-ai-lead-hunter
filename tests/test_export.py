"""Tests for the CRM CSV export endpoint (GET /export/csv)."""
from app.api.export import EXPORT_FIELDS


def test_export_csv(client):
    # 1. create a lead
    r = client.post(
        "/leads",
        json={
            "name": "Acme Die Casting",
            "website": "https://acme.com",
            "industry": "Die casting",
            "country": "USA",
        },
    )
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]

    # 2. run the rule-based analysis so products / score / priority exist
    a = client.post(f"/leads/{lead_id}/analyze")
    assert a.status_code == 200, a.text

    # 3. export
    resp = client.get("/export/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text

    # header + at least one data row
    assert ",".join(EXPORT_FIELDS) in body
    assert "Acme Die Casting" in body
    assert "https://acme.com" in body
    assert "USA" in body


def test_export_csv_header_columns():
    # sanity check on the documented column order (Phase 2.5 adds 4 CRM fields)
    assert EXPORT_FIELDS == [
        "company",
        "country",
        "website",
        "industry",
        "products",
        "email",
        "score",
        "reason",
        "priority",
        "lead_status",
        "email_status",
        "last_contact",
        "next_followup",
    ]
