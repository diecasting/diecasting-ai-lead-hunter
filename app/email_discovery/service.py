"""Email Discovery & Verification service (Phase 8).

Ties together the website crawler, pattern inference, ranking and the
verification pipeline, persisting results as :class:`EmailAddress` rows.
"""
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.email_discovery.crud import list_by_company, set_verification, upsert
from app.email_discovery.extractor import WebsiteEmailCrawler
from app.email_discovery.patterns import classify_email_type, infer_patterns
from app.email_discovery.verification import verify_email_address
from app.models.email_address import SOURCE_CRM, SOURCE_WEBSITE
from app.models.lead import CompanyLead


def company_domain(company: CompanyLead) -> str:
    """Best-effort registrable domain for a company (from ``domain`` or site)."""
    if company.domain:
        return company.domain.lower()
    if company.website:
        host = urlparse(company.website).hostname or ""
        return host.lower()
    return ""


def discover_for_company(
    db: Session,
    company: CompanyLead,
    *,
    fetcher=None,
    max_pages: int = 8,
    verify: bool = False,
    smtp_enabled: bool = True,
    catch_all_enabled: bool = True,
) -> List:
    """Crawl the company website, persist discovered + CRM e-mails.

    Steps:
      * crawl the company website (injectable ``fetcher``) for on-domain mails;
      * merge any e-mails already stored on the lead (``contact_email`` /
        ``contact_emails``) so CRM data is never lost;
      * optionally run the verification pipeline on every persisted address.

    Returns the list of persisted :class:`EmailAddress` rows.
    """
    domain = company_domain(company)
    found: List[str] = []

    # 1) Website crawl.
    if company.website:
        crawler = WebsiteEmailCrawler(
            company.website, fetcher=fetcher, max_pages=max_pages
        )
        found.extend(crawler.crawl())

    # 2) Existing CRM e-mails on the lead (don't lose them).
    crm_emails = list(company.contact_emails or [])
    if company.contact_email and company.contact_email not in crm_emails:
        crm_emails.append(company.contact_email)
    crm_emails = [e for e in crm_emails if e]

    rows = []
    for e in found:
        rows.append(
            upsert(
                db,
                company_id=company.id,
                email=e,
                source=SOURCE_WEBSITE,
                email_type=classify_email_type(e),
            )
        )
    for e in crm_emails:
        rows.append(
            upsert(
                db,
                company_id=company.id,
                email=e,
                source=SOURCE_CRM,
                email_type=classify_email_type(e),
            )
        )

    db.commit()

    if verify:
        for r in rows:
            res = verify_email_address(
                r.email,
                smtp_enabled=smtp_enabled,
                catch_all_enabled=catch_all_enabled,
            )
            set_verification(db, r, res)
        db.commit()

    return rows


def infer_company_patterns(company: CompanyLead, emails: List[str]) -> List[str]:
    """Return the inferred naming patterns for a company's known addresses."""
    domain = company_domain(company)
    if not domain:
        return []
    return infer_patterns(emails, domain)


def verify_emails(
    db: Session,
    *,
    company_id: Optional[int] = None,
    emails: Optional[List[str]] = None,
    smtp_enabled: bool = True,
    catch_all_enabled: bool = True,
) -> List:
    """Verify a list of e-mails, or all stored e-mails for a company.

    Returns a list of ``(EmailAddress, EmailVerificationResult)`` tuples.
    """
    targets = []
    if emails:
        for e in emails:
            if not e or "@" not in e:
                continue
            targets.append(
                upsert(
                    db,
                    company_id=company_id,
                    email=e,
                    source="manual",
                    email_type=classify_email_type(e),
                )
            )
    elif company_id is not None:
        targets = list_by_company(db, company_id)
    else:
        return []

    results = []
    for row in targets:
        res = verify_email_address(
            row.email,
            smtp_enabled=smtp_enabled,
            catch_all_enabled=catch_all_enabled,
        )
        set_verification(db, row, res)
        results.append((row, res))
    db.commit()
    return results
