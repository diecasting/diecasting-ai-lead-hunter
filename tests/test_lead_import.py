"""Tests for the bulk CSV / Excel lead import system (Phase 4 Stage 3.5).

Covers:
  * column mapping (company -> name, materials, process, business_type,
    contact_role, contact_name, contact_email, ...)
  * duplicate-company + duplicate-website skipping
  * missing-required-fields failures (empty company, no company column)
  * tolerance for extra/unknown CSV columns
  * CSV and Excel (.xlsx) parsing
  * dry-run preview that classifies rows WITHOUT persisting anything
  * persistence of mapped fields + lead_source="import"
  * manual lead creation -> lead_source="manual"
"""
import csv
import io

from fastapi.testclient import TestClient


def _csv_bytes(rows):
    buf = io.StringIO()
    fieldnames = []
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _post_csv(client, rows, name="leads.csv"):
    return client.post(
        "/leads/import", files={"file": (name, _csv_bytes(rows), "text/csv")}
    )


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
    r = _post_csv(client, rows)
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 4
    assert body["imported_count"] == 2
    assert body["skipped_count"] == 1
    assert body["failed_count"] == 1
    reasons = {e["reason"] for e in body["error_details"]}
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
    r = _post_csv(client, rows)
    assert r.status_code == 200
    body = r.json()
    assert body["imported_count"] == 1
    assert body["skipped_count"] == 1
    assert body["error_details"][0]["reason"] == "duplicate website"


def test_import_missing_required_fields(client: TestClient):
    """A CSV without the required `company` column fails every row."""
    rows = [
        {
            "country": "USA",
            "website": "https://no-company.example.com",
            "industry": "automotive",
            "contact_role": "Purchasing Manager",
        },
        {
            "country": "Germany",
            "website": "https://no-company2.example.com",
            "industry": "ev",
            "contact_role": "Engineer",
        },
    ]
    r = _post_csv(client, rows)
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 2
    assert body["imported_count"] == 0
    assert body["failed_count"] == 2
    assert all(
        e["reason"] == "missing company name" for e in body["error_details"]
    )
    assert all(e["row"] in (2, 3) for e in body["error_details"])


def test_import_extra_columns_ignored(client: TestClient):
    """Unknown columns (notes, phone, ...) must not fail the row."""
    rows = [
        {
            "company": "Extra Columns Co",
            "website": "https://extra.example.com",
            "notes": "internal note",
            "phone": "+1-555-0100",
            "industry": "automotive",
            "materials": "aluminum",
            "manufacturing_process": "high pressure die casting",
            "buying_signal": "looking for supplier",
            "contact_role": "Purchasing Manager",
        }
    ]
    r = _post_csv(client, rows)
    assert r.status_code == 200
    body = r.json()
    assert body["imported_count"] == 1
    assert body["failed_count"] == 0


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
    assert body["imported_count"] == 2
    assert body["skipped_count"] == 0
    assert body["failed_count"] == 0


def test_import_persists_mapped_fields_and_lead_source(client: TestClient):
    rows = [
        {
            "company": "Persist Co",
            "country": "Japan",
            "website": "https://persist.example.com",
            "industry": "electronics",
            "materials": "ADC12",
            "manufacturing_process": "squeeze casting",
            "business_type": "Manufacturer",
            "buying_signal": "expand line",
            "contact_role": "Procurement Lead",
            "contact_name": "Haruto Tanaka",
            "contact_email": "h.tanaka@persist.example.com",
        }
    ]
    r = _post_csv(client, rows)
    assert r.status_code == 200
    assert r.json()["imported_count"] == 1

    leads = client.get("/leads").json()
    by_name = {l["name"]: l for l in leads}
    assert "Persist Co" in by_name
    lead = by_name["Persist Co"]
    assert lead["materials"] == "ADC12"
    assert lead["manufacturing_process"] == "squeeze casting"
    assert lead["business_type"] == "Manufacturer"
    assert lead["contact_role"] == "Procurement Lead"
    assert lead["contact_name"] == "Haruto Tanaka"
    assert lead["contact_email"] == "h.tanaka@persist.example.com"
    assert lead["lead_source"] == "import"


def test_import_preview_does_not_write(client: TestClient):
    """The preview endpoint classifies rows but never persists them."""
    before = client.get("/leads").json()
    rows = [
        {
            "company": "Preview Co",
            "website": "https://preview.example.com",
            "industry": "automotive",
        },
        {
            "company": "Preview Co",  # intra-file duplicate
            "website": "https://preview-dup.example.com",
            "industry": "automotive",
        },
        {"country": "USA", "website": "https://preview-missing.example.com"},
    ]
    r = client.post(
        "/leads/import/preview",
        files={"file": ("leads.csv", _csv_bytes(rows), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 3
    assert body["valid_count"] == 1
    assert body["duplicate_count"] == 1
    assert body["failed_count"] == 1
    by_row = {p["row"]: p for p in body["rows"]}
    assert by_row[3]["status"] == "duplicate"
    assert by_row[3]["reason"] == "duplicate company"
    assert by_row[4]["status"] == "failed"
    assert by_row[4]["reason"] == "missing company name"

    after = client.get("/leads").json()
    assert len(after) == len(before), "preview must not create leads"


def test_manual_create_lead_source_manual(client: TestClient):
    r = client.post(
        "/leads",
        json={"name": "Manual Co", "website": "https://manual.example.com"},
    )
    assert r.status_code == 201
    assert r.json()["lead_source"] == "manual"
