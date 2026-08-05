"""Lead e-mail verification — MX record + syntax + SMTP availability (Phase 6.5).

Produces a lead-oriented :class:`VerificationResult` whose ``status`` is always
one of the three values the UI surfaces:

    valid    — address is syntactically OK and the domain has MX records; an
               SMTP probe (when possible) confirmed or did not disprove it.
    invalid  — address is undeliverable: bad syntax, or the domain has *no MX
               record* (hard block per requirement: never send to such a domain),
               or an SMTP probe proved the mailbox undeliverable.
    unknown  — inconclusive: the domain could not be probed (network blocked /
               timeout / greylisting) so we neither prove nor disprove it. An
               unknown result NEVER blocks a send.

Checks performed before any outreach send (requirement 1):
  1. **Syntax validation** — structural shape of ``local@domain.tld``.
  2. **Domain MX-record lookup** — real DNS ``MX`` query (``dns.resolver`` when
     available, ``getaddrinfo`` fallback). A *definitive* "no MX" answer
     (domain exists but publishes no MX) => ``invalid``. A lookup that could not
     be completed (network down / timeout) is inconclusive => ``unknown`` and
     does NOT block (we must not wrongly block a reachable domain just because
     our resolver is offline).
  3. **SMTP availability** — best-effort ``HELO`` / ``MAIL FROM`` / ``RCPT TO``
     probe against an MX host. Deliverable => ``valid``; undeliverable => ``invalid``;
     anything else (timeout / refused / greylist) => ``unknown``.

All network access is isolated behind injectable callables so the verifier is
fully unit-testable offline and never touches the real network unless asked.
"""
from typing import Callable, List, Optional

from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    BaseEmailVerifier,
    VerificationResult,
)
from app.outreach.verifiers import DisposableEmailChecker, SyntaxEmailVerifier

# Resolver contract: ``domain -> list[str]`` of MX hostnames, or ``None`` when
# the lookup could not be completed (inconclusive). ``[]`` means the domain was
# resolved but has no MX records (definitive).
MxResolver = Callable[[str], Optional[List[str]]]
# SMTP probe contract: ``(mx_host, email) -> "deliverable" | "undeliverable" |
# "unknown"``.
SmtpCheck = Callable[[str, str], str]

_DEFAULT_MX_TIMEOUT = 5.0
_DEFAULT_SMTP_TIMEOUT = 8.0


def resolve_mx(domain: str, *, timeout: float = _DEFAULT_MX_TIMEOUT) -> Optional[List[str]]:
    """Resolve MX records for ``domain``.

    Returns:
      * ``list[str]`` of MX hosts when the domain publishes MX records;
      * ``[]`` when the domain was resolved but publishes **no** MX records
        (a definitive "no mail exchanger" answer);
      * ``None`` when the lookup could not be completed (network down / timeout /
        resolver error) — i.e. *inconclusive*, not proof of absence.

    Uses ``dnspython`` when installed (authoritative ``MX`` records), otherwise
    falls back to a ``getaddrinfo`` heuristic. Never raises.
    """
    # Preferred: authoritative MX records via dnspython.
    try:
        import dns.resolver  # type: ignore
        from dns.resolver import NXDOMAIN, NoAnswer  # type: ignore

        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
            hosts = [str(r.exchange).rstrip(".").lower() for r in answers]
            if hosts:
                return hosts
            # Resolved without error but produced no MX records => definitive.
            return []
        except NoAnswer:
            # Domain exists but publishes no MX records — definitive "no MX".
            return []
        except NXDOMAIN:
            # Domain itself does not exist — cannot receive mail.
            return []
        except Exception:
            # Timeout / SERVFAIL / no nameservers — inconclusive.
            return None
    except Exception:
        pass

    # Fallback: if the bare domain resolves, treat it as a single MX target.
    # A resolution failure here is inconclusive (network issue), not proof of
    # absence, so we return None rather than [].
    try:
        import socket
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

        old = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            with ThreadPoolExecutor(max_workers=1) as ex:
                infos = ex.submit(socket.getaddrinfo, domain, None).result(
                    timeout=timeout + 1
                )
            if infos:
                return [domain]
            return []  # resolved but nothing came back — treat as no MX
        except (_FutTimeout, Exception):
            return None
        finally:
            socket.setdefaulttimeout(old)
    except Exception:
        return None


def smtp_probe(mx_host: str, email: str, *, timeout: float = _DEFAULT_SMTP_TIMEOUT) -> str:
    """Best-effort SMTP deliverability probe against ``mx_host`` (port 25).

    Performs ``EHLO`` -> ``MAIL FROM`` -> ``RCPT TO``. A ``250`` on ``RCPT TO``
    means deliverable; a ``5xx`` means undeliverable. Timeouts / connection
    refused / greylisting are inconclusive => ``unknown``. Never raises.
    """
    import smtplib

    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as server:
            server.ehlo()
            server.mail("verify@diecasting-ai-lead-hunter.local")
            code, _ = server.rcpt(email)
        if code == 250:
            return "deliverable"
        if code in (550, 551, 552, 553):
            return "undeliverable"
        return "unknown"
    except Exception:
        return "unknown"


def verify_lead_email(
    email: str,
    *,
    mx_resolver: Optional[MxResolver] = None,
    smtp_check: Optional[SmtpCheck] = None,
    smtp_enabled: bool = True,
) -> VerificationResult:
    """Verify ``email`` for lead outreach.

    Returns a :class:`VerificationResult` whose ``status`` is always one of
    ``{valid, invalid, unknown}`` (the three the UI surfaces), with a 0–100
    ``score`` and a ``detail["checks"]`` dict describing each step.
    """
    mx_resolver = mx_resolver or resolve_mx
    smtp_check = smtp_check or smtp_probe

    checks: dict = {}

    # 1) Syntax.
    syn = SyntaxEmailVerifier().verify(email)
    checks["syntax"] = syn.to_dict()
    if syn.status == INVALID:
        return VerificationResult(
            status=INVALID,
            verifier="lead_email",
            score=0,
            reason="email syntax is invalid",
            detail={"checks": list(checks.values())},
        )

    # 2) Domain MX records.
    domain = email.split("@", 1)[1].strip().lower()
    try:
        mx_hosts = mx_resolver(domain)
    except Exception:
        mx_hosts = None
    checks["mx"] = _mx_check_detail(domain, mx_hosts)
    # Requirement 4: block sending when the domain has NO MX records.
    if mx_hosts is not None and len(mx_hosts) == 0:
        return VerificationResult(
            status=INVALID,
            verifier="lead_email",
            score=15,
            reason=f"domain {domain} has no MX records",
            detail={"checks": list(checks.values())},
        )
    # Inconclusive MX lookup (None) — cannot prove absence, do not block.
    if mx_hosts is None:
        return VerificationResult(
            status=UNKNOWN,
            verifier="lead_email",
            score=50,
            reason=f"MX lookup for {domain} could not be completed (inconclusive)",
            detail={"checks": list(checks.values())},
        )

    # 3) SMTP availability (best effort — never hard-blocks on unknown).
    score = 85
    status = VALID
    if smtp_enabled:
        try:
            probe = smtp_check(mx_hosts[0], email)
        except Exception:
            probe = "unknown"
        checks["smtp"] = {
            "verifier": "smtp",
            "status": probe,
            "mx_host": mx_hosts[0],
            "reason": f"SMTP probe via {mx_hosts[0]}: {probe}",
        }
        if probe == "undeliverable":
            return VerificationResult(
                status=INVALID,
                verifier="lead_email",
                score=5,
                reason=f"SMTP probe reports mailbox undeliverable at {mx_hosts[0]}",
                detail={"checks": list(checks.values())},
            )
        if probe == "deliverable":
            score = 95
            status = VALID
        else:  # unknown / inconclusive
            score = 60
            status = UNKNOWN
    else:
        checks["smtp"] = {"verifier": "smtp", "status": "skipped",
                           "reason": "SMTP probe disabled"}

    # 4) Disposable / throwaway provider (soft — downgrades, never hard-blocks).
    disp = DisposableEmailChecker().verify(email)
    if disp.status == RISKY:
        checks["disposable"] = disp.to_dict()
        score = min(score, 30)
        if status == VALID:
            status = UNKNOWN

    return VerificationResult(
        status=status,
        verifier="lead_email",
        score=score,
        reason=checks["mx"]["reason"],
        detail={"checks": list(checks.values())},
    )


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


class LeadEmailVerifier(BaseEmailVerifier):
    """``BaseEmailVerifier`` wrapper so the lead verifier plugs into the gate."""

    name = "lead_email"

    def verify(self, email: str) -> VerificationResult:
        return verify_lead_email(email)
