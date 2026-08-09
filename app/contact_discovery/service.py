"""Contact Discovery Engine (Phase 13.2).

Orchestrates the four discovery sources and links every result back to the
existing data model *without* creating new tables:

  * **website**  -- crawl the company site for named people + on-domain mailboxes
  * **pdf**      -- mine downloadable PDFs (catalogs / spec sheets) for contacts
  * **pattern**  -- generate role inboxes (purchasing@, engineering@, …)

Every discovered contact is:
  * de-duplicated against existing ``contacts`` (by e-mail, then by name);
  * upserted as an :class:`EmailAddress` (provenance via ``discovery_method``);
  * linked to that :class:`EmailAddress` via ``email_address_id``;
  * scored deterministically (``discovery_score``) and labelled (``confidence``);
  * recorded in ``contact_discovery_logs`` for the TTL skip check.

Architecture reuse (no redesign):
  * :class:`app.email_discovery.extractor.WebsiteEmailCrawler` (website crawl)
  * :func:`app.crawler.pdf_extractor.discover_pdf_urls` / ``extract_pdf_text``
  * :func:`app.crawler.contact_extractor.extract_contacts` (name/title/email)
  * :func:`app.email_discovery.patterns.classify_email_type`
  * :func:`app.email_discovery.verification.verify_email_address`
  * :func:`app.contact_intelligence.scoring.score_contact` (purchasing intel)
  * :mod:`app.contact_discovery.scoring` (deterministic discovery score)

The outreach pipeline (Campaign / EmailQualityGate / EmailSender) is untouched —
this engine only *produces* enriched contacts.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

from sqlalchemy.orm import Session

from app.contact_discovery.role_patterns import (
    generate_role_inbox_emails,
    role_inbox_category,
    role_inbox_label,
)
from app.contact_discovery.scoring import classify_confidence, score_discovery
from app.contact_intelligence.scoring import (
    priority_from_score,
    score_contact,
    score_purchasing,
)
from app.models.contact import CATEGORY_OTHER, SENIORITY_UNKNOWN
from app.crawler.contact_extractor import extract_contacts
from app.crawler.email_extractor import extract_and_filter
from app.crawler.pdf_extractor import discover_pdf_urls, extract_pdf_text
from app.email_discovery.crud import set_verification, upsert
from app.email_discovery.extractor import WebsiteEmailCrawler
from app.email_discovery.patterns import classify_email_type
from app.email_discovery.service import company_domain
from app.email_discovery.verification import verify_email_address
from app.crud import contacts as contacts_crud
from app.models.contact import SOURCE_EMAIL_PATTERN, SOURCE_WEBSITE
from app.models.contact_discovery_log import (
    DISCOVERY_METHOD_PATTERN,
    DISCOVERY_METHOD_PDF,
    DISCOVERY_METHOD_WEBSITE,
    DISCOVERY_STATUS_DONE,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_SKIPPED,
    ContactDiscoveryLog,
)

# Pages worth probing for named contacts (mirrors WebsiteEmailCrawler paths).
_WEBSITE_PATHS = ["", "contact", "contact-us", "about", "about-us", "team"]

# How long a successful scan is considered "fresh" before we re-run it.
DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class ContactDiscoveryService:
    """Run the contact discovery engines for a company and persist results."""

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _domain(company) -> str:
        return company_domain(company)

    @staticmethod
    def _safe_fetch(fetcher, url: str) -> str:
        """Fetch ``url`` via ``fetcher`` returning decoded HTML (``""`` on any failure)."""
        if fetcher is None:
            return ""
        try:
            data = fetcher(url)
        except Exception:
            return ""
        if isinstance(data, str):
            return data
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", "ignore")
        return ""

    @staticmethod
    def _keep_email(email: Optional[str], domain: str) -> bool:
        """True when ``email`` is on-domain (or none); drops off-domain / customer mails."""
        if not email:
            return True
        if not domain:
            return True
        dom = email.split("@", 1)[1].lower()
        return dom == domain or dom.endswith("." + domain)

    @staticmethod
    def _website_pages(homepage: str) -> List[str]:
        base = (homepage or "").strip().rstrip("/")
        if not base.startswith("http://") and not base.startswith("https://"):
            base = "https://" + base
        urls: List[str] = []
        for p in _WEBSITE_PATHS:
            urls.append(base if p == "" else urljoin(base + "/", p))
        return urls

    # ------------------------------------------------------------- persist one
    def _persist_contact(
        self,
        db: Session,
        company,
        *,
        email: Optional[str],
        name: Optional[str] = None,
        title: Optional[str] = None,
        role: Optional[str] = None,
        source_url: Optional[str] = None,
        discovery_method: str,
        source: str,
        verify: bool = False,
        smtp_enabled: bool = True,
        catch_all_enabled: bool = True,
        seen_emails: set,
        seen_names: set,
    ) -> Optional[object]:
        """Create (or skip) one enriched Contact. Returns the Contact or ``None``."""
        # Off-domain e-mails (e.g. a customer referenced in a PDF) are dropped.
        if not self._keep_email(email, self._domain(company)):
            return None

        # De-dupe against this run's already-persisted records.
        key = (email or "").lower()
        if key and key in seen_emails:
            return None
        if name and name in seen_names:
            return None

        # Link / upsert the corporate e-mail address.
        email_row_id = None
        vstatus = None
        if email:
            etype = classify_email_type(email)
            email_row = upsert(
                db,
                company_id=company.id,
                email=email,
                source=source,
                email_type=etype,
            )
            # Provenance: which discovery engine found this address.
            email_row.discovery_method = discovery_method
            db.flush()
            if verify:
                res = verify_email_address(
                    email,
                    smtp_enabled=smtp_enabled,
                    catch_all_enabled=catch_all_enabled,
                )
                set_verification(db, email_row, res)
                vstatus = res.status
            email_row_id = email_row.id

        # Purchasing / intelligence fields.
        if title:
            intel = score_contact(title=title, source=source)
            title_category = intel["title_category"]
        else:
            title_category = (
                role_inbox_category(email) if email else CATEGORY_OTHER
            )
            purch = score_purchasing(title_category, SENIORITY_UNKNOWN, source)
            intel = {
                "title_category": title_category,
                "seniority": SENIORITY_UNKNOWN,
                "purchasing_score": purch,
                "priority": priority_from_score(purch),
            }

        dscore = score_discovery(
            verification_status=vstatus,
            source=discovery_method,
            title_category=title_category,
            is_pattern=(discovery_method == DISCOVERY_METHOD_PATTERN),
            has_email=bool(email),
        )
        confidence = classify_confidence(dscore)

        obj = contacts_crud.create(
            db,
            lead_id=company.id,
            full_name=name,
            title=title,
            role=role,
            email=email,
            email_address_id=email_row_id,
            source=source,
            source_url=source_url,
            discovery_method=discovery_method,
            title_category=title_category,
            seniority=intel["seniority"],
            purchasing_score=intel["purchasing_score"],
            priority=intel["priority"],
            discovery_score=dscore,
            confidence=confidence,
        )
        if key:
            seen_emails.add(key)
        if name:
            seen_names.add(name)
        return obj

    # ------------------------------------------------------------ log + TTL
    @staticmethod
    def _write_log(
        db: Session,
        company_id,
        domain: str,
        method: str,
        *,
        contacts_found: int = 0,
        emails_found: int = 0,
        status: str = DISCOVERY_STATUS_DONE,
        detail: Optional[str] = None,
    ) -> None:
        db.add(
            ContactDiscoveryLog(
                company_id=company_id,
                domain=domain,
                method=method,
                contacts_found=contacts_found,
                emails_found=emails_found,
                status=status,
                detail=detail,
            )
        )
        db.flush()

    def _already_scanned(
        self,
        db: Session,
        company_id,
        domain: str,
        method: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> bool:
        """True when a successful scan of ``(company, domain, method)`` is fresh."""
        if company_id is None or not domain:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
        return (
            db.query(ContactDiscoveryLog)
            .filter(
                ContactDiscoveryLog.company_id == company_id,
                ContactDiscoveryLog.domain == domain,
                ContactDiscoveryLog.method == method,
                ContactDiscoveryLog.status == DISCOVERY_STATUS_DONE,
                ContactDiscoveryLog.scanned_at >= cutoff,
            )
            .first()
            is not None
        )

    # ---------------------------------------------------------- source: website
    def extract_website_contacts(
        self,
        db: Session,
        company,
        *,
        fetcher: Optional[Callable[[str], object]] = None,
        seen_emails: set,
        seen_names: set,
        verify: bool = False,
        smtp_enabled: bool = True,
        catch_all_enabled: bool = True,
    ) -> List[object]:
        domain = self._domain(company)
        created: List[object] = []
        if not company.website:
            return created

        # 1) Named people from the high-value pages.
        for url in self._website_pages(company.website)[:8]:
            html = self._safe_fetch(fetcher, url)
            if not html:
                continue
            for c in extract_contacts(html, site_domain=domain):
                obj = self._persist_contact(
                    db,
                    company,
                    email=c.get("email"),
                    name=c.get("name"),
                    title=c.get("title"),
                    source_url=url,
                    discovery_method=DISCOVERY_METHOD_WEBSITE,
                    source=SOURCE_WEBSITE,
                    verify=verify,
                    smtp_enabled=smtp_enabled,
                    catch_all_enabled=catch_all_enabled,
                    seen_emails=seen_emails,
                    seen_names=seen_names,
                )
                if obj:
                    created.append(obj)

        # 2) Bare on-domain mailboxes surfaced by the crawler.
        crawler = WebsiteEmailCrawler(company.website, fetcher=fetcher)
        for email in crawler.crawl():
            obj = self._persist_contact(
                db,
                company,
                email=email,
                discovery_method=DISCOVERY_METHOD_WEBSITE,
                source=SOURCE_WEBSITE,
                verify=verify,
                smtp_enabled=smtp_enabled,
                catch_all_enabled=catch_all_enabled,
                seen_emails=seen_emails,
                seen_names=seen_names,
            )
            if obj:
                created.append(obj)
        return created

    # -------------------------------------------------------------- source: pdf
    def extract_pdf_contacts(
        self,
        db: Session,
        company,
        *,
        fetcher: Optional[Callable[[str], object]] = None,
        text_extractor: Optional[Callable[[bytes], str]] = None,
        seen_emails: set,
        seen_names: set,
        verify: bool = False,
        smtp_enabled: bool = True,
        catch_all_enabled: bool = True,
    ) -> List[object]:
        domain = self._domain(company)
        created: List[object] = []
        if not company.website:
            return created

        home_html = self._safe_fetch(fetcher, company.website)
        # discover_pdf_urls expects an HTML-returning fetcher (it scans pages for
        # ``.pdf`` links). The injected ``fetcher`` may return PDF *bytes* for a
        # discovered ``.pdf`` URL, so wrap it to always hand back decoded text —
        # mirroring how the existing PDFExtractor decodes before discovery. The
        # raw (bytes) fetcher is still used below to fetch each PDF's content.
        def page_fetcher(url: str) -> str:
            try:
                data = fetcher(url)
            except Exception:
                return ""
            if isinstance(data, (bytes, bytearray)):
                return data.decode("utf-8", "ignore")
            return data or ""

        try:
            pdf_urls = discover_pdf_urls(
                company.website, html=home_html, fetcher=page_fetcher
            )
        except Exception:
            pdf_urls = []

        for url in pdf_urls:
            try:
                raw = fetcher(url)
            except Exception:
                continue
            if not isinstance(raw, (bytes, bytearray)):
                continue  # skip HTML / non-PDF responses
            text = extract_pdf_text(raw, text_extractor=text_extractor)
            if not text:
                continue
            for c in extract_contacts(text, site_domain=domain):
                email = c.get("email")
                # Reject off-domain (customer) e-mails mined from a PDF.
                if email and not self._keep_email(email, domain):
                    continue
                obj = self._persist_contact(
                    db,
                    company,
                    email=email,
                    name=c.get("name"),
                    title=c.get("title"),
                    source_url=url,
                    discovery_method=DISCOVERY_METHOD_PDF,
                    source=SOURCE_WEBSITE,
                    verify=verify,
                    smtp_enabled=smtp_enabled,
                    catch_all_enabled=catch_all_enabled,
                    seen_emails=seen_emails,
                    seen_names=seen_names,
                )
                if obj:
                    created.append(obj)
        return created

    # ----------------------------------------------------------- source: pattern
    def generate_email_candidates(
        self,
        db: Session,
        company,
        *,
        seen_emails: set,
        seen_names: set,
        verify: bool = False,
        smtp_enabled: bool = True,
        catch_all_enabled: bool = True,
    ) -> List[object]:
        domain = self._domain(company)
        created: List[object] = []
        for email in generate_role_inbox_emails(domain):
            obj = self._persist_contact(
                db,
                company,
                email=email,
                role=role_inbox_label(email),
                discovery_method=DISCOVERY_METHOD_PATTERN,
                source=SOURCE_EMAIL_PATTERN,
                verify=verify,
                smtp_enabled=smtp_enabled,
                catch_all_enabled=catch_all_enabled,
                seen_emails=seen_emails,
                seen_names=seen_names,
            )
            if obj:
                created.append(obj)
        return created

    # --------------------------------------------------------------- orchestrate
    def discover_company_contacts(
        self,
        db: Session,
        company,
        *,
        fetcher: Optional[Callable[[str], object]] = None,
        text_extractor: Optional[Callable[[bytes], str]] = None,
        verify: bool = False,
        smtp_enabled: bool = True,
        catch_all_enabled: bool = True,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Dict:
        """Run all enabled discovery engines and persist enriched contacts.

        Returns a summary dict keyed by method (``website`` / ``pdf`` / ``role``)
        with ``status`` and ``contacts_created`` (and ``total_contacts_created``).
        Fresh successful scans (within ``ttl_seconds``) are skipped.
        """
        domain = self._domain(company)
        existing = contacts_crud.list_for_lead(db, company.id)
        seen_emails = {c.email.lower() for c in existing if c.email}
        seen_names = {c.full_name for c in existing if c.full_name}

        summary: Dict = {}

        # Website -----------------------------------------------------------
        summary["website"] = self._run_method(
            db,
            company,
            DISCOVERY_METHOD_WEBSITE,
            self.extract_website_contacts,
            domain,
            ttl_seconds,
            fetcher=fetcher,
            seen_emails=seen_emails,
            seen_names=seen_names,
            verify=verify,
            smtp_enabled=smtp_enabled,
            catch_all_enabled=catch_all_enabled,
        )

        # PDF ---------------------------------------------------------------
        if company.website:
            summary["pdf"] = self._run_method(
                db,
                company,
                DISCOVERY_METHOD_PDF,
                self.extract_pdf_contacts,
                domain,
                ttl_seconds,
                fetcher=fetcher,
                text_extractor=text_extractor,
                seen_emails=seen_emails,
                seen_names=seen_names,
                verify=verify,
                smtp_enabled=smtp_enabled,
                catch_all_enabled=catch_all_enabled,
            )
        else:
            summary["pdf"] = {
                "status": DISCOVERY_STATUS_SKIPPED,
                "contacts_created": 0,
                "detail": "no website",
            }

        # Pattern / role inboxes ------------------------------------------
        summary["role"] = self._run_method(
            db,
            company,
            DISCOVERY_METHOD_PATTERN,
            self.generate_email_candidates,
            domain,
            ttl_seconds,
            seen_emails=seen_emails,
            seen_names=seen_names,
            verify=verify,
            smtp_enabled=smtp_enabled,
            catch_all_enabled=catch_all_enabled,
        )

        db.commit()
        summary["total_contacts_created"] = sum(
            s.get("contacts_created", 0)
            for s in summary.values()
            if isinstance(s, dict)
        )
        return summary

    # -------------------------------------------------------------- run wrapper
    def _run_method(
        self, db, company, method, fn, domain, ttl_seconds, *args, **kwargs
    ) -> Dict:
        if self._already_scanned(db, company.id, domain, method, ttl_seconds):
            return {"status": "skipped_ttl", "contacts_created": 0}
        try:
            created = fn(db, company, *args, **kwargs)
            emails_found = sum(1 for c in created if getattr(c, "email", None))
            self._write_log(
                db,
                company.id,
                domain,
                method,
                contacts_found=len(created),
                emails_found=emails_found,
                status=DISCOVERY_STATUS_DONE,
            )
            return {
                "status": DISCOVERY_STATUS_DONE,
                "contacts_created": len(created),
                "emails_found": emails_found,
            }
        except Exception as exc:  # never abort the other engines
            self._write_log(
                db,
                company.id,
                domain,
                method,
                contacts_found=0,
                emails_found=0,
                status=DISCOVERY_STATUS_FAILED,
                detail=str(exc),
            )
            return {"status": DISCOVERY_STATUS_FAILED, "error": str(exc)}
