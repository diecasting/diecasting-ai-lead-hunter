"""LLM provider abstraction (Phase 9 AI Sales Agent).

This is the *only* place that knows about a concrete LLM provider. Every other
module in the agent calls :func:`complete_json` and degrades gracefully to the
deterministic template path when no provider is configured or a call fails.

Keeping the provider behind this one function satisfies the "keep LLM provider
abstraction" requirement: to swap providers (e.g. a self-hosted model) you only
edit ``settings`` + this module. Network / auth failures are swallowed so the
rest of the system stays deterministic and testable offline — tests simply
monkeypatch :func:`complete_json` to simulate AI output without any network.
"""
import json
from typing import Any, Dict, Optional

from app.config import settings


def provider_name() -> str:
    """The configured provider key (currently ``openai``)."""
    return getattr(settings, "ai_provider", "openai") or "openai"


def llm_enabled() -> bool:
    """True when AI enhancement is allowed *and* a provider is configured."""
    if not getattr(settings, "ai_sales_agent_use_llm", True):
        return False
    if provider_name() == "openai":
        return bool(getattr(settings, "openai_api_key", ""))
    return False


def complete_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Best-effort JSON completion. Returns the parsed dict, or ``None``.

    Returns ``None`` when AI is disabled, no provider key is set, or the call
    raises for any reason. Callers must treat ``None`` as "use the deterministic
    fallback".
    """
    if not llm_enabled():
        return None
    try:
        if provider_name() == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key)
            kwargs: Dict[str, Any] = dict(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            resp = client.chat.completions.create(**kwargs)
            return json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return None
    return None
