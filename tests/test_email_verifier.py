"""Tests for email verifiers + outreach quality gate (Phase 4 Stage 0).

Covers:
  * BaseEmailVerifier interface + VerificationResult helpers
  * SyntaxEmailVerifier (valid / invalid / role-account risky)
  * MxEmailVerifier with an injected fake resolver (has-mx / no-mx / error)
  * DisposableEmailChecker (built-in list + injected domains)
  * EmailQualityGate aggregate verdict + do_not_contact blocking
"""
from app.outreach.email_verifier import (
    INVALID,
    RISKY,
    UNKNOWN,
    VALID,
    BaseEmailVerifier,
    VerificationResult,
)
from app.outreach.quality_gate import EmailQualityGate
from app.outreach.verifiers import (
    DisposableEmailChecker,
    MxEmailVerifier,
    SyntaxEmailVerifier,
    default_verifier_chain,
)


# ---------------------------------------------------------------------------
# Base interface + result
# ---------------------------------------------------------------------------
class _DummyVerifier(BaseEmailVerifier):
    name = "dummy"

    def __init__(self, result):
        self._result = result

    def verify(self, email: str) -> VerificationResult:
        return self._result


class TestBaseAndResult:
    def test_result_defaults_deliverability(self):
        r = VerificationResult(status=VALID)
        assert r.is_deliverable == "yes"
        r2 = VerificationResult(status=INVALID)
        assert r2.is_deliverable == "no"
        r3 = VerificationResult(status=RISKY)
        assert r3.is_deliverable == "unknown"

    def test_result_is_blocked(self):
        # Stage 1: only INVALID is a hard block; RISKY is a soft signal.
        assert VerificationResult(status=INVALID).is_blocked() is True
        assert VerificationResult(status=RISKY).is_blocked() is False
        assert VerificationResult(status=VALID).is_blocked() is False
        assert VerificationResult(status=UNKNOWN).is_blocked() is False

    def test_callable_alias(self):
        d = _DummyVerifier(VerificationResult(status=VALID))
        assert d("a@b.com").status == VALID

    def test_to_dict_roundtrip(self):
        r = VerificationResult(status=RISKY, verifier="x", reason="r", score=10)
        d = r.to_dict()
        assert d["status"] == RISKY and d["verifier"] == "x"


# ---------------------------------------------------------------------------
# Syntax verifier
# ---------------------------------------------------------------------------
class TestSyntaxVerifier:
    def test_valid_address(self):
        r = SyntaxEmailVerifier().verify("buyer@acme.com")
        assert r.status == VALID
        assert r.score == 100

    def test_invalid_no_at(self):
        r = SyntaxEmailVerifier().verify("notanemail")
        assert r.status == INVALID

    def test_invalid_double_dot(self):
        r = SyntaxEmailVerifier().verify("a..b@acme.com")
        assert r.status == INVALID

    def test_invalid_tld_too_short(self):
        r = SyntaxEmailVerifier().verify("a@acme.c")
        assert r.status == INVALID

    def test_role_account_is_risky(self):
        r = SyntaxEmailVerifier().verify("info@acme.com")
        assert r.status == RISKY
        assert "role" in r.reason.lower()

    def test_empty_is_invalid(self):
        r = SyntaxEmailVerifier().verify("")
        assert r.status == INVALID

    def test_local_part_len_guard(self):
        long_local = "a" * 65 + "@acme.com"
        r = SyntaxEmailVerifier().verify(long_local)
        assert r.status == INVALID


# ---------------------------------------------------------------------------
# MX verifier (injectable resolver)
# ---------------------------------------------------------------------------
class TestMxVerifier:
    def test_has_mx_valid(self):
        v = MxEmailVerifier(resolver=lambda domain: True)
        r = v.verify("buyer@acme.com")
        assert r.status == VALID
        assert r.score == 90

    def test_no_mx_risky(self):
        v = MxEmailVerifier(resolver=lambda domain: False)
        r = v.verify("buyer@acme.com")
        assert r.status == RISKY

    def test_resolver_error_unknown(self):
        def boom(domain):
            raise RuntimeError("dns down")

        v = MxEmailVerifier(resolver=boom)
        r = v.verify("buyer@acme.com")
        assert r.status == UNKNOWN

    def test_no_domain_invalid(self):
        v = MxEmailVerifier(resolver=lambda d: True)
        r = v.verify("no-at-sign")
        assert r.status == INVALID


# ---------------------------------------------------------------------------
# Disposable checker
# ---------------------------------------------------------------------------
class TestDisposableChecker:
    def test_known_disposable_risky(self):
        r = DisposableEmailChecker().verify("spam@mailinator.com")
        assert r.status == RISKY
        assert "disposable" in r.reason.lower()

    def test_normal_domain_valid(self):
        r = DisposableEmailChecker().verify("buyer@acme.com")
        assert r.status == VALID

    def test_injected_domain(self):
        v = DisposableEmailChecker(domains=["throwaway.example"])
        r = v.verify("user@throwaway.example")
        assert r.status == RISKY

    def test_builtin_extended_not_replaced(self):
        v = DisposableEmailChecker(domains=["extra.example"])
        assert "mailinator.com" in v._domains
        assert "extra.example" in v._domains


# ---------------------------------------------------------------------------
# Composite quality gate
# ---------------------------------------------------------------------------
class TestQualityGate:
    def test_valid_passes(self):
        g = EmailQualityGate()
        r = g.check("buyer@acme.com")
        assert r.status == VALID
        assert "checks" in r.detail

    def test_invalid_wins_over_others(self):
        # syntax fails -> aggregate must be invalid even if MX/disposable pass
        g = EmailQualityGate()
        r = g.check("not-an-email")
        assert r.status == INVALID

    def test_disposable_is_risky_soft_signal(self):
        """Stage 1: disposable -> RISKY verdict but NOT a hard block by default."""
        g = EmailQualityGate()
        r = g.check("spam@mailinator.com")
        assert r.status == RISKY
        assert r.is_blocked() is False

    def test_disposable_risky_hard_blocked_when_opt_in(self):
        g = EmailQualityGate(block_risky=True)
        r = g.allow_send("spam@mailinator.com")
        assert r.status == INVALID
        assert r.is_blocked() is True

    def test_do_not_contact_blocks(self):
        class L:
            do_not_contact = True

        g = EmailQualityGate()
        r = g.allow_send("buyer@acme.com", lead=L())
        assert r.status == INVALID
        assert "do_not_contact" in r.reason.lower()

    def test_do_not_contact_on_contact_blocks(self):
        class C:
            do_not_contact = True

        g = EmailQualityGate()
        r = g.allow_send("buyer@acme.com", contact=C())
        assert r.is_blocked() is True

    def test_force_override(self):
        g = EmailQualityGate()
        r = g.allow_send("spam@mailinator.com", force=True)
        assert r.status == VALID
        assert r.is_blocked() is False

    def test_injected_verifier_chain(self):
        # Custom chain: only syntax, so disposable address should pass.
        chain = [SyntaxEmailVerifier()]
        g = EmailQualityGate(verifiers=chain)
        r = g.check("spam@mailinator.com")
        assert r.status == VALID

    def test_default_verifier_chain_has_three(self):
        assert len(default_verifier_chain()) == 3
