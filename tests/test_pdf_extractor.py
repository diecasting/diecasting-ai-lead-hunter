"""Tests for the PDF capability extractor (Phase 2.3, section 4).

Uses injectable fetcher and text_extractor stubs so no network or real PDF
parsing is required.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crawler.pdf_extractor import (
    PDFExtractionResult,
    PDFExtractor,
    analyze_capabilities,
    discover_pdf_urls,
    extract_pdf_text,
)
from app.database import Base
from app.models.company_document import CompanyDocument
from app.models.lead import CompanyLead


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def lead(db):
    obj = CompanyLead(
        name="TestDieCast Co",
        website="https://example-diecast.com",
        domain="example-diecast.com",
        country="USA",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ---------------------------------------------------------------------------
# discover_pdf_urls
# ---------------------------------------------------------------------------
class TestDiscoverPdfUrls:
    def test_finds_pdf_links_in_html(self):
        html = """
        <html><body>
          <a href="/catalog/brochure.pdf">Brochure</a>
          <a href="/about">About</a>
          <a href="https://example.com/docs/spec.pdf">Spec</a>
        </body></html>
        """
        urls = discover_pdf_urls("https://example.com", html=html)
        assert any("brochure.pdf" in u for u in urls)
        assert any("spec.pdf" in u for u in urls)

    def test_no_pdf_links(self):
        html = '<html><body><a href="/about">About</a></body></html>'
        urls = discover_pdf_urls("https://example.com", html=html)
        assert urls == []

    def test_uses_fetcher_to_probe_paths(self):
        """When a fetcher is provided, canonical PDF-host paths are probed."""
        html = '<html><body><a href="/products">Products</a></body></html>'
        catalog_html = '<html><body><a href="/catalog/full.pdf">Full Catalog</a></body></html>'

        def fetcher(url):
            if "/catalog" in url:
                return catalog_html
            return ""

        urls = discover_pdf_urls("https://example.com", html=html, fetcher=fetcher)
        assert any("full.pdf" in u for u in urls)

    def test_deduplicates_urls(self):
        html = """
        <html><body>
          <a href="/catalog/brochure.pdf">Brochure</a>
          <a href="/catalog/brochure.pdf">Brochure Again</a>
        </body></html>
        """
        urls = discover_pdf_urls("https://example.com", html=html)
        pdf_urls = [u for u in urls if "brochure.pdf" in u]
        assert len(pdf_urls) == 1


# ---------------------------------------------------------------------------
# analyze_capabilities
# ---------------------------------------------------------------------------
class TestAnalyzeCapabilities:
    def test_detects_machine_capacity(self):
        text = "Our machines have a clamping force of 800 tons and 400 tonne capacity."
        caps = analyze_capabilities(text)
        assert len(caps["machine_capacity"]) >= 2

    def test_detects_tolerance(self):
        text = "We achieve tolerances of ±0.05 mm and ±0.1mm consistently."
        caps = analyze_capabilities(text)
        assert len(caps["tolerance"]) >= 2

    def test_detects_materials(self):
        text = "We work with aluminum, magnesium, and ADC12 alloys."
        caps = analyze_capabilities(text)
        assert "aluminum" in caps["materials"]
        assert "magnesium" in caps["materials"]
        assert "adc12" in caps["materials"]

    def test_detects_certifications(self):
        text = "We are certified to IATF 16949, ISO 9001, and RoHS standards."
        caps = analyze_capabilities(text)
        assert "IATF 16949" in caps["certifications"]
        assert "ISO 9001" in caps["certifications"]
        assert "RoHS" in caps["certifications"]

    def test_detects_industries(self):
        text = "We serve automotive, aerospace, and robotics industries."
        caps = analyze_capabilities(text)
        assert "automotive" in caps["industries"]
        assert "aerospace" in caps["industries"]
        assert "robotics" in caps["industries"]

    def test_empty_text(self):
        caps = analyze_capabilities("")
        assert caps["machine_capacity"] == []
        assert caps["tolerance"] == []
        assert caps["materials"] == []
        assert caps["certifications"] == []
        assert caps["industries"] == []


# ---------------------------------------------------------------------------
# extract_pdf_text
# ---------------------------------------------------------------------------
class TestExtractPdfText:
    def test_uses_injected_extractor(self):
        def fake_extractor(raw_bytes):
            return "Extracted text from PDF"

        result = extract_pdf_text(b"fake bytes", text_extractor=fake_extractor)
        assert result == "Extracted text from PDF"

    def test_injected_extractor_receives_bytes(self):
        received = []

        def capture_extractor(raw_bytes):
            received.append(raw_bytes)
            return "text"

        extract_pdf_text(b"pdf content", text_extractor=capture_extractor)
        assert received == [b"pdf content"]


# ---------------------------------------------------------------------------
# PDFExtractor (integration with DB)
# ---------------------------------------------------------------------------
class TestPDFExtractor:
    def test_extracts_and_persists_documents(self, db, lead):
        """Full pipeline: discover → fetch → extract → persist → merge capabilities."""
        pdf_urls = ["https://example-diecast.com/catalog/brochure.pdf"]
        pdf_text = """
        We are an aluminum die casting manufacturer.
        Clamping force: 800 tons. Tolerance: ±0.05 mm.
        Certified to IATF 16949 and ISO 9001.
        Serving automotive and EV industries.
        """

        # Stub fetcher: returns HTML for page probes, returns bytes for PDF URLs.
        def fake_fetcher(url):
            if url.endswith(".pdf"):
                return b"fake pdf bytes"
            # For page probes, return HTML that links to the PDF.
            return f'<html><body><a href="{pdf_urls[0]}">Brochure</a></body></html>'

        def fake_text_extractor(raw_bytes):
            return pdf_text

        extractor = PDFExtractor(
            fetcher=fake_fetcher, text_extractor=fake_text_extractor, max_docs=5
        )
        result = extractor.extract_for_lead(db, lead, home_html="")

        assert result.status == "success"
        assert len(result.documents) >= 1
        assert "aluminum" in result.materials_found
        assert "IATF 16949" in result.certifications_found

        # Verify CompanyDocument rows were persisted.
        from app.crud import company_documents as doc_crud
        docs = doc_crud.get_by_lead(db, lead.id)
        assert len(docs) >= 1
        assert any("brochure.pdf" in d.url for d in docs)

    def test_skips_lead_without_website(self, db):
        lead = CompanyLead(name="No Website Co", website=None)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        extractor = PDFExtractor()
        result = extractor.extract_for_lead(db, lead, home_html="")
        assert result.status == "skipped"
        assert "no website" in result.error

    def test_no_documents_found(self, db, lead):
        """When no PDF links are discovered, status is 'no_documents'."""
        html = '<html><body><a href="/about">About</a></body></html>'

        def fake_fetcher(url):
            return html  # No PDF links anywhere

        extractor = PDFExtractor(fetcher=fake_fetcher)
        result = extractor.extract_for_lead(db, lead, home_html=html)
        assert result.status == "no_documents"

    def test_merges_materials_onto_lead(self, db, lead):
        """Materials discovered in PDFs are merged onto the lead's materials field."""
        pdf_text = "We use aluminum, magnesium, and ADC12 for die casting."

        def fake_fetcher(url):
            if url.endswith(".pdf"):
                return b"fake"
            return '<html><body><a href="/cat.pdf">Cat</a></body></html>'

        extractor = PDFExtractor(
            fetcher=fake_fetcher,
            text_extractor=lambda raw: pdf_text,
        )
        extractor.extract_for_lead(db, lead, home_html="")

        db.refresh(lead)
        assert lead.materials is not None
        assert "aluminum" in lead.materials
        assert "magnesium" in lead.materials

    def test_result_to_dict(self, db, lead):
        extractor = PDFExtractor()
        result = extractor.extract_for_lead(db, lead, home_html="")
        d = result.to_dict()
        assert "lead_id" in d
        assert "documents" in d
        assert "status" in d
