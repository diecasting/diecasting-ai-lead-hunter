"""Contact Intelligence service (Phase 8.5).

Ties together the website contact crawler, the existing CRM lead fields and the
Phase 8 EmailAddress rows, then classifies titles and scores every contact by
purchasing-decision relevance. Persists results as :class:`Contact` rows (on
the existing ``contacts`` table, extended in Phase 8.5).
"""
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.contact_intelligence import crud
from app.contact_intelligence.extractor import WebsiteContactCrawler
from app.contact_intelligence.scoring import score_contact
from app.models.contact import SOURCE_CRM, SOURCE_EMAIL_PATTERN, SOURCE_WEBSITE
from app.models.email_address import TYPE_PERSONAL, EmailAddress
from app.models.lead import CompanyLead


def company_domain(company: CompanyLead) -> str:
    """Best-effort registrable domain for a company (from ``domain`` or site)."""
    if company.domain:
        return company.domain.lower()
    if company.website:
        host = urlparse(company.website).hostname or ""
        return host.lower()
    return ""


def _name_from_email(local_part: str) -> str:
    """Turn an e-mail local-part into a display name, e.g. ``john.smith`` ->
    ``John Smith``. Falls back to the raw token capitalised."""
    if not local_part:
        return ""
    # Split on common separators; drop empty tokens and pure-digit tokens.
    tokens = [t for t in local_part.replace("_", ".").split(".") if t and not t.isdigit()]
    if not tokens:
        return local_part.capitalize()
    if len(tokens) == 1:
        return tokens[0].capitalize()
    # Use the first two tokens (first name + surname) for a clean display name.
    return " ".join(t.capitalize() for t in tokens[:2])


def _classify_and_persist(db: Session, contact) -> None:
    """Classify + score a single contact and persist the intelligence fields."""
    intel = score_contact(title=contact.title, source=contact.source or SOURCE_WEBSITE)
    crud.set_intelligence(
        db,
        contact,
        title_category=intel["title_category"],
        seniority=intel["seniority"],
        purchasing_score=intel["purchasing_score"],
        priority=intel["priority"],
    )


def discover_for_company(
    db: Session,
    company: CompanyLead,
    *,
    fetcher=None,
    max_pages: int = 8,
    classify: bool = True,
    score: bool = True,
) -> List:
    """Discover contacts for a company from three sources and persist them:

      1. **Website** — crawl the company site for people/contact blocks.
      2. **CRM**      — the lead's ``contact_name`` / ``contact_email`` /
         ``contact_emails`` / ``contact_role`` (never lose stored data).
      3. **Email pattern** — personal e-mails already discovered by the Phase 8
         Email Discovery engine become inferred contact candidates.

    When ``classify`` / ``score`` are enabled, every touched contact is also
    classified (title -> category + seniority) and scored by purchasing
    priority. Returns the list of *touched* :class:`Contact` rows.
    """
    touched_ids: List[int] = []

    # 1) Website crawl.
    if company.website:
        crawler = WebsiteContactCrawler(
            company.website, fetcher=fetcher, max_pages=max_pages
        )
        for c in crawler.crawl():
            name = c.get("name")
            email = c.get("email")
            if not name and not email:
                continue
            obj = crud.upsert(
                db,
                lead_id=company.id,
                full_name=name,
                email=email,
                title=c.get("title"),
                source=SOURCE_WEBSITE,
            )
            if obj.id not in touched_ids:
                touched_ids.append(obj.id)

    # 2) CRM lead fields.
    crm_emails = list(company.contact_emails or [])
    if company.contact_email and company.contact_email not in crm_emails:
        crm_emails.append(company.contact_email)
    crm_emails = [e for e in crm_emails if e]
    crm_name = company.contact_name
    for email in crm_emails:
        name = crm_name or _name_from_email(email.split("@", 1)[0])
        obj = crud.upsert(
            db,
            lead_id=company.id,
            full_name=name,
            email=email,
            title=company.contact_role,
            source=SOURCE_CRM,
        )
        if obj.id not in touched_ids:
            touched_ids.append(obj.id)

    # 3) Personal e-mails discovered by the Phase 8 Email Discovery engine.
    personal_emails = (
        db.query(EmailAddress)
        .filter(
            EmailAddress.company_id == company.id,
            EmailAddress.email_type == TYPE_PERSONAL,
        )
        .all()
    )
    for row in personal_emails:
        local = row.email.split("@", 1)[0] if row.email else ""
        name = _name_from_email(local)
        obj = crud.upsert(
            db,
            lead_id=company.id,
            full_name=name,
            email=row.email,
            source=SOURCE_EMAIL_PATTERN,
            email_address_id=row.id,
        )
        if obj.id not in touched_ids:
            touched_ids.append(obj.id)

    # Classify + score every touched contact.
    if classify or score:
        for cid in touched_ids:
            contact = crud.get(db, cid)
            if contact is not None:
                _classify_and_persist(db, contact)

    # Return the touched rows (freshly classified / scored).
    result = []
    for cid in touched_ids:
        obj = crud.get(db, cid)
        if obj is not None:
            result.append(obj)
    return result


def score_company_contacts(db: Session, company_id: int) -> List:
    """Re-run title classification + purchasing scoring on every existing
    contact for a company (re-prioritisation). Returns the updated rows."""
    contacts = crud.list_for_company(db, company_id)
    for contact in contacts:
        _classify_and_persist(db, contact)
    return contacts
