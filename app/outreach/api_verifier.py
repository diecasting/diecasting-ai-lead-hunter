"""API-based e-mail verifier abstraction (Phase 4 Stage 1).

Extends :class:`BaseEmailVerifier` with an ``api_call`` boundary so a concrete
verifier can delegate the actual lookup to an external email-verification
service (ZeroBounce, NeverBounce, MillionVerifier, an internal micro-service,
etc.) while keeping the same ``verify() -> VerificationResult`` contract.

The HTTP/network call lives entirely behind the ``api_call`` method, which is
injectable — so tests can supply a canned response without any real network
traffic. ``ApiEmailVerifier`` is *abstract*; subclasses implement ``api_call``
and (optionally) ``_map_response`` to translate the provider JSON into a
:class:`VerificationResult`.
"""
from abc import abstractmethod
from typing import Callable, Dict, Optional

from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    BaseEmailVerifier,
    VerificationResult,
)

# Canonical provider status vocabulary -> our verdict.
# Providers vary; we normalise a handful of common tokens.
_PROVIDER_STATUS_TO_VERDICT = {
    "valid": VALID,
    "deliverable": VALID,
    "ok": VALID,
    "true": VALID,
    "invalid": INVALID,
    "undeliverable": INVALID,
    "bad": INVALID,
    "false": INVALID,
    "risky": RISKY,
    "unknown": UNKNOWN,
    "accept_all": RISKY,
    "catch_all": RISKY,
    "role": RISKY,
    "disposable": RISKY,
    "free": RISKY,
    "do_not_mail": INVALID,
    "spamtrap": INVALID,
}


class ApiEmailVerifier(BaseEmailVerifier):
    """Abstract base for verifiers backed by an external verification API.

    Subclasses MUST implement :meth:`api_call`. They MAY override
    :meth:`_map_response` to translate provider-specific JSON into a
    :class:`VerificationResult` (the default handles a common shape).
    """

    #: Stable verifier name (override in subclasses, e.g. "zerobounce").
    name = "api"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout

    @abstractmethod
    def api_call(self, email: str) -> Dict:
        """Perform the provider lookup and return the raw response dict.

        Implementations should raise on transport failure; :meth:`verify` will
        convert exceptions into an ``UNKNOWN`` result rather than crashing.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Response mapping (override per provider)
    # ------------------------------------------------------------------
    def _map_response(self, email: str, resp: Dict) -> VerificationResult:
        """Translate a provider response dict into a VerificationResult.

        Recognised keys (case-insensitive): ``status`` / ``result``,
        ``deliverable`` (bool), ``score`` / ``confidence`` (0–100),
        ``reason`` / ``sub_status`` / ``error``.
        """
        status_raw = (
            str(resp.get("status") or resp.get("result") or resp.get("state") or "")
        ).strip().lower()
        verdict = _PROVIDER_STATUS_TO_VERDICT.get(status_raw, UNKNOWN)

        # Boolean deliverable hint takes precedence for hard decisions.
        deliverable = resp.get("deliverable")
        if isinstance(deliverable, bool):
            verdict = VALID if deliverable else INVALID
        elif deliverable in ("yes", "true", "1"):
            verdict = VALID
        elif deliverable in ("no", "false", "0"):
            verdict = INVALID

        score = None
        for key in ("score", "confidence", "quality_score"):
            if resp.get(key) is not None:
                try:
                    score = int(float(resp[key]))
                except (TypeError, ValueError):
                    score = None
                break

        reason = (
            resp.get("reason")
            or resp.get("sub_status")
            or resp.get("error")
            or status_raw
            or "api verification"
        )
        if isinstance(reason, (list, tuple)):
            reason = ", ".join(str(r) for r in reason)

        return VerificationResult(
            status=verdict,
            verifier=self.name,
            reason=str(reason),
            score=score,
            detail={"provider_response": resp},
        )

    def verify(self, email: str) -> VerificationResult:
        try:
            resp = self.api_call(email)
            return self._map_response(email, resp or {})
        except Exception as exc:  # pragma: no cover - network dependent
            return VerificationResult(
                status=UNKNOWN,
                verifier=self.name,
                reason=f"api verification error: {exc}",
                score=50,
            )


class MockApiEmailVerifier(ApiEmailVerifier):
    """Test double: an ``ApiEmailVerifier`` driven by an injected responder.

    ``responder`` is ``(email) -> dict`` (or a plain dict used for every call).
    No network is touched. Useful for unit tests and offline runs.
    """

    name = "mock_api"

    def __init__(
        self,
        responder: Optional[Callable[[str], Dict]] = None,
        fixed_response: Optional[Dict] = None,
    ) -> None:
        super().__init__(api_key="test")
        if fixed_response is not None and responder is None:
            responder = lambda _e: fixed_response  # noqa: E731
        self._responder = responder or (lambda _e: {"status": "unknown"})

    def api_call(self, email: str) -> Dict:
        return self._responder(email)
