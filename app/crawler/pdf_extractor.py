"""PDF capability extractor (Phase 2.3, section 4).

Discovers a company's downloadable documents (catalogs / brochures / spec PDFs)
by probing the canonical asset paths (``/download``, ``/catalog``, ``/brochure``,
``/pdf`` …), fetches the PDF bytes, extracts plain text, and mines capability
signals:

* machine capacity  (clamp tonnage / kN)
* tolerance         (± mm / μm)
* materials         (from ``app.ai.keywords``)
* certifications    (IATF 16949, ISO 9001, RoHS, …)
* industries        (from ``app.ai.keywords``)

Extracted documents are persisted to the ``company_documents`` table and the
mined materials / processes are merged back onto the parent ``CompanyLead``.

The network layer (``fetcher``) and the PDF→text layer (``text_extractor``) are
both injectable, so the discovery / capability logic is fully testable without a
browser or a real PDF parser.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from sqlalchemy.orm import Session

from app.ai.scoring import (
    detect_industries,
    detect_materials,
    detect_processes,
)
from app.crawler.page_discovery import extract_links

# Canonical paths that typically host downloadable documents.
PDF_PATH_HINTS = ["/download", "/catalog", "/brochure", "/pdf", "/resources", "/media"]

# Path keyword tokens that hint a page links to PDFs.
PDF_PATH_TOKENS = ["download", "catalog", "brochure", "pdf", "resource", "media", "doc"]

PDF_EXT_RE = re.compile(r"\.pdf($|\?|#)", re.IGNORECASE)

# Capability regexes ---------------------------------------------------------
CAPACITY_RE = re.compile(
    r"(\d[\d,]*)\s*(ton|tons|tonne|tonnes|t|kn)\b", re.IGNORECASE
)
TOLERANCE_RE = re.compile(
    r"(±|\+/-)?\s*(\d+\.?\d*)\s*(mm|μm|um|micron|microns)\b", re.IGNORECASE
)

CERT_PATTERNS = [
    ("IATF 16949", r"iatf\s*16949"),
    ("ISO 9001", r"iso\s*9001"),
    ("ISO/TS 16949", r"iso\s*/?\s*ts\s*16949"),
    ("ISO 14001", r"iso\s*14001"),
    ("ISO 45001", r"iso\s*45001"),
    ("RoHS", r"rohs"),
    ("REACH", r"reach"),
]


def _is_pdf_link(href: str) -> bool:
    return bool(PDF_EXT_RE.search(href or ""))


def discover_pdf_urls(
    home_url: str, html: str = "", fetcher: Optional[Callable[[str], str]] = None
) -> List[str]:
    """Return de-duplicated absolute PDF URLs discovered around ``home_url``.

    Strategy: scan the provided ``html`` (usually the homepage), then probe each
    canonical PDF-host path and any same-domain link whose path looks PDF-ish,
    collecting every ``.pdf`` href found.
    """
    domain = (urlparse(home_url).hostname or "").lower()
    base = home_url.rstrip("/")
    found: List[str] = []

    def scan(page_html: str) -> None:
        for link in extract_links(page_html or "", base_domain=domain):
            if _is_pdf_link(link) and link not in found:
                found.append(link)

    # 1. Scan whatever HTML we already have (typically the homepage).
    scan(html)

    # 2. Candidate PDF-host pages (canonical) + any discovered PDF-ish links.
    pages_to_visit: List[str] = []
    seen_pages: set = set()
    for path in PDF_PATH_HINTS:
        url = urljoin(base + "/", path.lstrip("/"))
        if url not in seen_pages:
            seen_pages.add(url)
            pages_to_visit.append(url)

    for link in extract_links(html or "", base_domain=domain):
        p = urlparse(link).path.lower()
        if any(tok in p for tok in PDF_PATH_TOKENS):
            if link not in seen_pages:
                seen_pages.add(link)
                pages_to_visit.append(link)

    if fetcher is not None:
        for page_url in pages_to_visit:
            try:
                page_html = fetcher(page_url)
            except Exception:
                continue
            scan(page_html)

    return found


def analyze_capabilities(text: str) -> Dict[str, object]:
    """Mine capability signals from extracted PDF text."""
    capacity = [m.group(0).strip() for m in CAPACITY_RE.finditer(text or "")]
    tolerance = [m.group(0).strip().replace(" ", "") for m in TOLERANCE_RE.finditer(text or "")]

    certs: List[str] = []
    low = (text or "").lower()
    for label, pattern in CERT_PATTERNS:
        if re.search(pattern, low, re.IGNORECASE):
            certs.append(label)

    return {
        "machine_capacity": capacity,
        "tolerance": tolerance,
        "materials": detect_materials(text),
        "certifications": certs,
        "industries": detect_industries(text),
        "processes": detect_processes(text),
    }


def extract_pdf_text(pdf_bytes: bytes, text_extractor=None) -> str:
    """Extract plain text from PDF bytes.

    ``text_extractor`` is injectable for tests; otherwise we lazily import
    ``pdfminer.six`` (declared in requirements.txt for production use).
    """
    if text_extractor is not None:
        return text_extractor(pdf_bytes)
    from pdfminer.high_level import extract_text

    # pdfminer expects a path or file-like; wrap bytes in a BytesIO buffer.
    from io import BytesIO

    return extract_text(BytesIO(pdf_bytes)) or ""


@dataclass
class PDFExtractionResult:
    lead_id: int
    documents: List[Dict] = field(default_factory=list)
    materials_found: List[str] = field(default_factory=list)
    processes_found: List[str] = field(default_factory=list)
    certifications_found: List[str] = field(default_factory=list)
    status: str = "success"
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "documents": self.documents,
            "materials_found": self.materials_found,
            "processes_found": self.processes_found,
            "certifications_found": self.certifications_found,
            "status": self.status,
            "error": self.error,
        }


class PDFExtractor:
    """Discover, fetch and mine a lead's downloadable documents."""

    def __init__(
        self,
        fetcher: Optional[Callable[[str], bytes]] = None,
        text_extractor: Optional[Callable[[bytes], str]] = None,
        max_docs: int = 5,
    ):
        self._fetcher = fetcher  # url -> bytes
        self._text_extractor = text_extractor  # bytes -> str
        self.max_docs = max_docs

    # Public API -------------------------------------------------------------
    def extract_for_lead(
        self, db: Session, lead, home_html: str = ""
    ) -> PDFExtractionResult:
        """Run discovery + extraction for one lead and persist the documents."""
        from app.crud import company_documents as doc_crud

        result = PDFExtractionResult(lead_id=lead.id)
        if not lead.website:
            result.status = "skipped"
            result.error = "lead has no website"
            return result

        try:
            pdf_urls = discover_pdf_urls(lead.website, html=home_html, fetcher=self._fetch_html)
        except Exception as exc:
            result.status = "failed"
            result.error = f"discovery failed: {exc}"
            return result

        if not pdf_urls:
            result.status = "no_documents"
            return result

        all_materials: set = set()
        all_processes: set = set()
        all_certs: set = set()

        for url in pdf_urls[: self.max_docs]:
            if doc_crud.get_by_url(db, url):
                continue  # already ingested
            try:
                raw = self._fetch_pdf(url)
                text = extract_pdf_text(raw, text_extractor=self._text_extractor)
            except Exception:
                continue
            if not text:
                continue
            caps = analyze_capabilities(text)
            doc_crud.create(
                db, lead_id=lead.id, url=url, file_type="pdf", content=text[:20000]
            )
            result.documents.append(
                {"url": url, "file_type": "pdf", "capabilities": caps}
            )
            all_materials.update(caps.get("materials") or [])
            all_processes.update(caps.get("processes") or [])
            all_certs.update(caps.get("certifications") or [])

        # Merge mined materials / processes back onto the lead.
        if all_materials or all_processes:
            self._merge_lead_capabilities(db, lead, all_materials, all_processes)

        result.materials_found = sorted(all_materials)
        result.processes_found = sorted(all_processes)
        result.certifications_found = sorted(all_certs)
        db.commit()
        return result

    # Injectable fetchers ----------------------------------------------------
    def _fetch_html(self, url: str) -> str:
        if self._fetcher is not None:
            # fetcher may return bytes or str; normalise to str HTML.
            data = self._fetcher(url)
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="ignore")
            return data
        raise RuntimeError("no HTML fetcher configured")

    def _fetch_pdf(self, url: str) -> bytes:
        if self._fetcher is not None:
            data = self._fetcher(url)
            if isinstance(data, str):
                return data.encode("utf-8")
            return data
        raise RuntimeError("no PDF fetcher configured")

    # Helpers ----------------------------------------------------------------
    @staticmethod
    def _merge_lead_capabilities(db, lead, materials: set, processes: set) -> None:
        existing_materials = {
            m.strip() for m in (lead.materials or "").split(",") if m.strip()
        }
        existing_processes = {
            p.strip() for p in (lead.manufacturing_process or "").split(",") if p.strip()
        }
        merged_materials = existing_materials | materials
        merged_processes = existing_processes | processes
        if merged_materials:
            lead.materials = ", ".join(sorted(merged_materials))
        if merged_processes:
            lead.manufacturing_process = ", ".join(sorted(merged_processes))
        db.add(lead)


def extract_pdf_documents(
    db: Session, lead, home_html: str = "", fetcher=None, text_extractor=None
) -> dict:
    """Convenience helper: run ``PDFExtractor`` for a lead and return a dict."""
    extractor = PDFExtractor(fetcher=fetcher, text_extractor=text_extractor)
    return extractor.extract_for_lead(db, lead, home_html=home_html).to_dict()
