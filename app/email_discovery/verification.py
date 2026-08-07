"""E-mail verification pipeline (Phase 8).

Orchestrates the *existing* outreach verification primitives
(``SyntaxEmailVerifier``, ``DisposableEmailChecker``, ``resolve_mx``,
``smtp_probe``) and adds **catch-all domain detection**, which was missing from
the Phase 6.5 verifier. All network access is injected (or looked up at call
time from ``app.outreach.lead_email_verifier``) so the pipeline is fully
unit-testable offline and the ``conftest`` network-isolation patch propagates.

Produces an :class:`EmailVerificationResult` carrying the shared
``verification_status`` vocabulary (valid / invalid / risky / unknown) plus a
0–100 ``verification_score`` and a ``catch_all`` flag.
"""
import random
import string
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
)
from app.outreach import lead_email_verifier as _lev_mod
from app.outreach.verifiers import DisposableEmailChecker, SyntaxEmailVerifier

# Resolver / probe are looked up on the ``lead_email_verifier`` module *at call
# time* (not bound at import) so the conftest network-isolation patch and
# per-test monkeypatches take effect in one place.
# A random local-part that almost certainly does NOT exist, used to probe for
# catch-all domains.
_CATCHALL_TOKEN_LEN = 12


def _random_local() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=_CATCHALL_TOKEN_LEN))


@dataclass
class EmailVerificationResult:
    """Outcome of the Phase 8 verification pipeline for one address."""

    status: str                       # valid | invalid | risky | unknown
    score: int                       # 0-100
    is_deliverable: Optional[str]    # yes | no | unknown
    reason: str
    catch_all: bool = False
    checks: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "verification_status": self.status,
            "verification_score": self.score,
            "is_deliverable": self.is_deliverable,
            "reason": self.reason,
            "catch_all": self.catch_all,
            "checks": self.checks,
        }


def detect_catch_all(
    domain: str, mx_host: str, smtp_check: Callable[[str, str], str]
) -> bool:
    """Return True when ``domain``'s MX accepts mail for arbitrary local-parts.

    Implementation: probe a randomly-generated (almost certainly non-existent)
    local-part. A ``deliverable`` response indicates a catch-all domain, which
    makes individual-address verification less trustworthy.
    """
    probe = smtp_check(mx_host, f"{_random_local()}@{domain}")
    return probe == "deliverable"


def _mx_check_detail(domain: str, mx_hosts: Optional[List[str]]) -> dict:
    if mx_hosts is None:
        return {
            "verifier": "mx",
            "status": UNKNOWN,
            "mx_records": [],
            "reason": f"MX lookup for {domain} could not be completed (inconclusive)",
        }
    if len(mx_hosts) == 0:
        return {
            "verifier": "mx",
            "status": INVALID,
            "mx_records": [],
            "reason": f"domain {domain} has no MX records",
        }
    return {
        "verifier": "mx",
        "status": VALID,
        "mx_records": mx_hosts,
        "reason": f"domain {domain} has {len(mx_hosts)} MX record(s)",
    }


def verify_email_address(
    email: str,
    *,
    mx_resolver: Optional[Callable[[str], Optional[List[str]]]] = None,
    smtp_check: Optional[Callable[[str, str], str]] = None,
    smtp_enabled: bool = True,
    catch_all_enabled: bool = True,
) -> EmailVerificationResult:
    """Run the full verification pipeline for a single address.

    Checks (in order):
      1. **syntax** validation (reused ``SyntaxEmailVerifier``).
      2. **disposable** provider detection (reused ``DisposableEmailChecker``)
         — soft downgrade, never hard-blocks.
      3. **MX** record lookup (reused ``resolve_mx``): ``[]`` => invalid
         (hard block), ``None`` => unknown (do not block).
      4. **SMTP** probe (reused ``smtp_probe``): deliverable => valid,
         undeliverable => invalid, anything else => unknown.
      5. **catch-all** detection (NEW): a random non-existent local-part probe;
         if deliverable, the domain is catch-all and the verdict is softened.
    """
    mx_resolver = mx_resolver or _lev_mod.resolve_mx
    smtp_check = smtp_check or _lev_mod.smtp_probe

    checks: List[Dict] = []
    catch_all = False

    # 1) Syntax.
    syn = SyntaxEmailVerifier().verify(email)
    checks.append(syn.to_dict())
    if syn.status == INVALID:
        return EmailVerificationResult(
            status=INVALID,
            score=0,
            is_deliverable="no",
            reason="email syntax is invalid",
            checks=checks,
        )

    domain = email.split("@", 1)[1].strip().lower()

    # 2) Disposable provider (soft — downgrade, never hard-block).
    disp = DisposableEmailChecker().verify(email)
    checks.append(disp.to_dict())
    disposable = disp.status == RISKY

    # 3) MX records.
    try:
        mx_hosts = mx_resolver(domain)
    except Exception:
        mx_hosts = None
    checks.append(_mx_check_detail(domain, mx_hosts))
    if mx_hosts is None:
        # Inconclusive — cannot prove absence, do not block.
        return EmailVerificationResult(
            status=UNKNOWN,
            score=50,
            is_deliverable="unknown",
            reason=f"MX lookup for {domain} could not be completed (inconclusive)",
            checks=checks,
        )
    if len(mx_hosts) == 0:
        return EmailVerificationResult(
            status=INVALID,
            score=15,
            is_deliverable="no",
            reason=f"domain {domain} has no MX records",
            checks=checks,
        )

    # 4) SMTP probe (best-effort).
    score = 85
    status = VALID
    if smtp_enabled:
        try:
            probe = smtp_check(mx_hosts[0], email)
        except Exception:
            probe = "unknown"
        checks.append(
            {
                "verifier": "smtp",
                "status": probe,
                "mx_host": mx_hosts[0],
                "reason": f"SMTP probe via {mx_hosts[0]}: {probe}",
            }
        )
        if probe == "undeliverable":
            return EmailVerificationResult(
                status=INVALID,
                score=5,
                is_deliverable="no",
                reason=f"SMTP probe reports mailbox undeliverable at {mx_hosts[0]}",
                checks=checks,
            )
        if probe == "deliverable":
            score = 95
        else:  # unknown / inconclusive
            score = 60
            status = UNKNOWN
    else:
        checks.append(
            {"verifier": "smtp", "status": "skipped", "reason": "SMTP probe disabled"}
        )

    # 5) Catch-all detection (uses a random non-existent local-part).
    if catch_all_enabled and smtp_enabled:
        try:
            catch_all = detect_catch_all(domain, mx_hosts[0], smtp_check)
        except Exception:
            catch_all = False
        checks.append(
            {
                "verifier": "catch_all",
                "status": "catch-all" if catch_all else "normal",
                "reason": (
                    "domain accepts mail for any local-part (catch-all)"
                    if catch_all
                    else "domain is not catch-all"
                ),
            }
        )
        if catch_all:
            # Catch-all domains make individual verification less trustworthy.
            score = max(20, score - 25)
            if status == VALID:
                status = UNKNOWN

    # 6) Fold in the disposable downgrade.
    if disposable:
        score = min(score, 30)
        if status == VALID:
            status = UNKNOWN

    is_deliverable = (
        "yes" if status == VALID else ("no" if status == INVALID else "unknown")
    )
    return EmailVerificationResult(
        status=status,
        score=max(0, min(100, score)),
        is_deliverable=is_deliverable,
        reason=checks[-1].get("reason", ""),
        catch_all=catch_all,
        checks=checks,
    )
