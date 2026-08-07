"""EmailAddress ORM model — Phase 8 Email Discovery & Verification Engine.

Stores every e-mail address discovered or inferred for a company / lead, along
with its provenance (``source``), semantic category (``email_type``) and the
latest deliverability verdict from the verification pipeline
(``verification_status`` / ``verification_score`` / ``verified_at``).

The ``verification_status`` vocabulary deliberately re-uses the outreach
verifier verdicts (valid / invalid / risky / unknown) and adds an explicit
``unverified`` starting state for freshly discovered addresses that have not
yet been run through the pipeline.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Verification status vocabulary
# ---------------------------------------------------------------------------
VERIFICATION_UNVERIFIED = "unverified"
VERIFICATION_VALID = "valid"
VERIFICATION_INVALID = "invalid"
VERIFICATION_RISKY = "risky"
VERIFICATION_UNKNOWN = "unknown"

VERIFICATION_STATUSES = [
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VALID,
    VERIFICATION_INVALID,
    VERIFICATION_RISKY,
    VERIFICATION_UNKNOWN,
]

# ---------------------------------------------------------------------------
# Provenance (where the address came from)
# ---------------------------------------------------------------------------
SOURCE_WEBSITE = "website"   # extracted by crawling the company website
SOURCE_CRM = "crm"           # already on the lead (contact_email / contact_emails)
SOURCE_PATTERN = "pattern"   # inferred from a naming pattern + domain
SOURCE_MANUAL = "manual"     # entered / verified explicitly by an operator

SOURCES = [SOURCE_WEBSITE, SOURCE_CRM, SOURCE_PATTERN, SOURCE_MANUAL]

# ---------------------------------------------------------------------------
# Semantic category of the mailbox
# ---------------------------------------------------------------------------
TYPE_PERSONAL = "personal"   # looks like a named individual (john.smith)
TYPE_ROLE = "role"           # role / generic inbox (sales, info, support)
TYPE_GENERIC = "generic"     # other corporate mailbox

EMAIL_TYPES = [TYPE_PERSONAL, TYPE_ROLE, TYPE_GENERIC]


class EmailAddress(Base):
    """A discovered / inferred e-mail address belonging to a company lead."""

    __tablename__ = "email_addresses"
    __table_args__ = (
        Index("ix_email_addresses_company_email", "company_id", "email", unique=True),
        Index("ix_email_addresses_company_status", "company_id", "verification_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)
    source = Column(
        String(40), nullable=False, default=SOURCE_WEBSITE, server_default=SOURCE_WEBSITE
    )
    email_type = Column(
        String(20), nullable=False, default=TYPE_GENERIC, server_default=TYPE_GENERIC
    )
    verification_status = Column(
        String(20),
        nullable=False,
        default=VERIFICATION_UNVERIFIED,
        server_default=VERIFICATION_UNVERIFIED,
        index=True,
    )
    verification_score = Column(Integer, nullable=True, index=True)  # 0-100
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EmailAddress id={self.id} email={self.email!r} "
            f"status={self.verification_status!r}>"
        )
