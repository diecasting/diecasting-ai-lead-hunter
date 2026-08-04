"""Concrete e-mail verifiers (Phase 4 Stage 0).

All three verifiers implement :class:`BaseEmailVerifier` from
``app.outreach/email_verifier.py`` and are fully deterministic / mockable:

* ``SyntaxEmailVerifier`` — RFC-5322-ish local-part / domain shape check.
* ``MxEmailVerifier``     — DNS MX-record lookup, with an injectable resolver
                            so tests (and offline runs) never hit the network.
* ``DisposableEmailChecker`` — matches the domain against a disposable /
                            throwaway e-mail provider list (built-in + injectable).

Network dependencies are isolated behind constructor-injected callables so the
verifiers can be unit-tested in isolation.
"""
import re
from typing import Callable, Dict, Iterable, List, Optional, Set

from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    BaseEmailVerifier,
    VerificationResult,
)

# Local-part: letters/digits and a limited punctuation set, no leading/trailing
# dot, no consecutive dots, <= 64 chars. Domain: dot-separated labels, TLD >= 2.
_SYNTAX_RE = re.compile(
    r"^(?=.{3,254}$)"                      # overall length guard
    r"(?=[^@]{1,64}@)"                     # local-part <= 64 chars
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)

# Role / generic mailboxes that are deliverable but undesirable for 1:1 outreach.
_ROLE_LOCAL_PARTS = {
    "admin", "info", "support", "sales", "billing", "abuse", "postmaster",
    "webmaster", "noreply", "no-reply", "donotreply", "help", "contact",
    "office", "hello", "team", "marketing",
}

# A modest built-in disposable / throwaway provider list. Real deployments can
# inject a larger, externally maintained list (see ``DisposableEmailChecker``).
_BUILTIN_DISPOSABLE_DOMAINS: Set[str] = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.info", "sharklasers.com",
    "10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org",
    "throwawaymail.com", "getnada.com", "nada.email", "maildrop.cc", "yopmail.com",
    "yopmail.net", "trashmail.com", "trashmail.net", "fakeinbox.com", "mailnesia.com",
    "dispostable.com", "mohmal.com", "tempmailo.com", "tmpmail.org", "emailondeck.com",
    "spam4.me", "grr.la", "guerrillamailblock.com", "pokemail.net", "spambog.com",
    "tempinbox.com", "mailcatch.com", "mailnull.com", "jetable.org", "mintemail.com",
}


class SyntaxEmailVerifier(BaseEmailVerifier):
    """Structural validation of an e-mail address (no network)."""

    name = "syntax"

    def verify(self, email: str) -> VerificationResult:
        if not email or not isinstance(email, str):
            return VerificationResult(
                status=INVALID, verifier=self.name, reason="empty or non-string email",
                score=0,
            )
        addr = email.strip()
        if not _SYNTAX_RE.match(addr):
            return VerificationResult(
                status=INVALID, verifier=self.name,
                reason="does not match email syntax (local-part@domain.tld)",
                score=0,
            )
        local = addr.split("@", 1)[0].lower()
        if local in _ROLE_LOCAL_PARTS:
            # Deliverable but a generic inbox — flag as risky, not invalid.
            return VerificationResult(
                status=RISKY, verifier=self.name,
                reason=f"role/generic mailbox '{local}' is rarely a real person",
                score=40,
            )
        return VerificationResult(
            status=VALID, verifier=self.name,
            reason="syntax OK", score=100,
        )


class MxEmailVerifier(BaseEmailVerifier):
    """DNS MX-record existence check for the address domain.

    ``resolver`` is an injectable callable ``(domain) -> bool`` returning True
    when the domain has at least one MX record. The default uses
    ``socket.getaddrinfo`` as a lightweight stand-in (a domain that resolves at
    all is very likely to accept mail); tests should inject a fake resolver.
    """

    name = "mx"

    def __init__(self, resolver: Optional[Callable[[str], bool]] = None) -> None:
        self._resolver = resolver or self._default_resolver

    @staticmethod
    def _default_resolver(domain: str) -> bool:
        import socket

        try:
            socket.getaddrinfo(domain, None)
            return True
        except Exception:
            return False

    def verify(self, email: str) -> VerificationResult:
        if not email or "@" not in email:
            return VerificationResult(
                status=INVALID, verifier=self.name, reason="no domain to resolve",
                score=0,
            )
        domain = email.split("@", 1)[1].strip().lower()
        try:
            has_mx = bool(self._resolver(domain))
        except Exception:
            # Resolution failure is inconclusive, not proof of invalidity.
            return VerificationResult(
                status=UNKNOWN, verifier=self.name,
                reason=f"MX lookup for {domain} failed/indeterminate",
                score=50,
            )
        if has_mx:
            return VerificationResult(
                status=VALID, verifier=self.name,
                reason=f"domain {domain} has MX records", score=90,
            )
        return VerificationResult(
            status=RISKY, verifier=self.name,
            reason=f"domain {domain} has no resolvable MX records",
            score=30,
        )


class DisposableEmailChecker(BaseEmailVerifier):
    """Flags disposable / throwaway e-mail providers as risky."""

    name = "disposable"

    def __init__(
        self, domains: Optional[Iterable[str]] = None
    ) -> None:
        # Built-in set is always active; caller can extend with a larger list.
        self._domains: Set[str] = set(_BUILTIN_DISPOSABLE_DOMAINS)
        if domains:
            self._domains.update(d.lower() for d in domains)

    def verify(self, email: str) -> VerificationResult:
        if not email or "@" not in email:
            return VerificationResult(
                status=INVALID, verifier=self.name, reason="no domain to inspect",
                score=0,
            )
        domain = email.split("@", 1)[1].strip().lower()
        if domain in self._domains:
            return VerificationResult(
                status=RISKY, verifier=self.name,
                reason=f"disposable / throwaway provider ({domain})",
                score=10,
            )
        return VerificationResult(
            status=VALID, verifier=self.name,
            reason="not a known disposable provider", score=100,
        )


def default_verifier_chain() -> List[BaseEmailVerifier]:
    """Return the standard ordered verifier list used by the quality gate."""
    return [
        SyntaxEmailVerifier(),
        DisposableEmailChecker(),
        MxEmailVerifier(),
    ]
