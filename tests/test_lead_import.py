"""Tests for the bulk CSV / Excel lead import endpoint (Phase 4).

Covers:
  * column mapping (company -> name, materials, process, role, ...)
  * duplicate-company + duplicate-website skipping
  * missing-company-name failures
  * CSV and Excel (.xlsx) parsing
  * persistence of mapped fields + source="csv_import"
"""
import csv
import io

from fastapi.testclient import TestClient


def _csv_bytes(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def test_import_csv_counts_and_dedup(client: TestClient):
    rows = [
        {
            "company": "Acme Casting Inc",
            "country": "USA",
            "website": "https://acme.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "looking for supplier",
            "contact_role": "Purchasing Manager",
        },
        {
            "company": "Beta Metalworks",
            "country": "Germany",
            "website": "https://beta.example.com",
            "industry": "ev",
            "materials": "zinc",
            "manufacturing_process": "low pressure die casting",
            "buying_signal": "sourcing capacity",
            "contact_role": "Engineering Manager",
        },
        # duplicate company name -> skipped
        {
            "company": "Acme Casting Inc",
            "country": "USA",
            "website": "https://acme2.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "",
            "contact_role": "Purchasing Manager",
        },
        # missing company name -> failed
        {
            "company": "",
            "country": "USA",
            "website": "https://nodup.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "",
            "contact_role": "Purchasing Manager",
        },
    ]
    r = client.post(
        "/leads/import", files={"file": ("leads.csv", _csv_bytes(rows), "text/csv")}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["imported"] == 2
    assert body["skipped"] == 1
    assert body["failed"] == 1
    reasons = {e["reason"] for e in body["errors"]}
    assert "duplicate company" in reasons
    assert "missing company name" in reasons


def test_import_duplicate_website_skipped(client: TestClient):
    rows = [
        {
            "company": "First Co",
            "country": "USA",
            "website": "https://shared.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "",
            "contact_role": "Purchasing Manager",
        },
        {
            "company": "Second Co",  # different name, same website -> skip
            "country": "USA",
            "website": "https://shared.example.com",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "",
            "contact_role": "Purchasing Manager",
        },
    ]
    r = client.post(
        "/leads/import", files={"file": ("leads.csv", _csv_bytes(rows), "text/csv")}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert body["errors"][0]["reason"] == "duplicate website"


def test_import_xlsx_basic(client: TestClient):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "company",
            "country",
            "website",
            "industry",
            "materials",
            "manufacturing_process",
            "buying_signal",
            "contact_role",
        ]
    )
    ws.append(
        [
            "Gamma Forge Ltd",
            "France",
            "https://gamma.example.com",
            "aerospace",
            "magnesium",
            "gravity die casting",
            "quote",
            "Supplier Quality Manager",
        ]
    )
    ws.append(
        [
            "Delta Precision",
            "Italy",
            "https://delta.example.com",
            "hydraulic",
            "aluminum",
            "vacuum die casting",
            "dual-source",
            "Strategic Sourcing",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post(
        "/leads/import",
        files={
            "file": (
                "leads.xlsx",
                buf.read(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["failed"] == 0


def test_import_persists_mapped_fields(client: TestClient):
    rows = [
        {
            "company": "Persist Co",
            "country": "Japan",
            "website": "https://persist.example.com",
            "industry": "electronics",
            "materials": "ADC12",
            "manufacturing_process": "squeeze casting",
            "buying_signal": "expand line",
            "contact_role": "Procurement Lead",
        }
    ]
    r = client.post(
        "/leads/import", files={"file": ("leads.csv", _csv_bytes(rows), "text/csv")}
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 1

    leads = client.get("/leads").json()
    by_name = {l["name"]: l for l in leads}
    assert "Persist Co" in by_name
    assert by_name["Persist Co"]["materials"] == "ADC12"
    assert by_name["Persist Co"]["manufacturing_process"] == "squeeze casting"
    assert by_name["Persist Co"]["contact_role"] == "Procurement Lead"
    assert by_name["Persist Co"]["source"] == "csv_import"
