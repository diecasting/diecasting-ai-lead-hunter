"""Question discovery for the Phase 7 Authority Engine.

Discovers Quora questions relevant to an industrial keyword. The search
resolver is injectable so the rest of the system (and the test-suite) runs
fully offline; the default resolver uses the configured search provider
(SerpAPI / Google) and degrades gracefully to ``[]`` when the network or
provider is unavailable (e.g. the sandbox, where no key is configured).
"""
from typing import Callable, List, Optional

# A candidate dict: {"question_text", "quora_url", "topic", "tags"}
QuestionCandidate = dict


def _default_question_resolver(keyword: str, limit: int = 20) -> List[QuestionCandidate]:
    """Resolve real Quora question pages via the configured search provider."""
    try:
        from app.search.service import default_provider

        provider = default_provider()
        results = provider.search(
            f"{keyword} quora question", country="us", max_results=limit
        )
        candidates: List[QuestionCandidate] = []
        for r in results or []:
            url = (r.url or "").strip()
            if "quora.com" not in url.lower():
                continue
            candidates.append(
                {
                    "question_text": (r.title or "").strip() or url,
                    "quora_url": url,
                    "topic": keyword,
                }
            )
        return candidates
    except Exception:
        # No network / no provider / provider error -> return nothing rather
        # than raising, so the discovery endpoint stays safe in dry-run.
        return []


def discover_questions(
    keyword: str,
    *,
    resolver: Optional[Callable[[str], List[QuestionCandidate]]] = None,
    limit: int = 20,
) -> List[QuestionCandidate]:
    """Discover Quora question candidates for ``keyword``.

    Args:
        keyword: industrial topic to search (e.g. "die casting defects").
        resolver: injectable callable returning raw candidate dicts. When
            ``None`` the default search-provider resolver is used.
        limit: maximum candidates to return.

    Returns:
        Deduplicated list of candidate dicts.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    raw = resolver(keyword) if resolver is not None else _default_question_resolver(
        keyword, limit=limit
    )

    out: List[QuestionCandidate] = []
    seen: set = set()
    for c in raw or []:
        url = (c.get("quora_url") or "").strip()
        text = (c.get("question_text") or "").strip()
        if not text and not url:
            continue
        key = url or text
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "question_text": text or url,
                "quora_url": url or None,
                "topic": (c.get("topic") or keyword).strip(),
                "tags": c.get("tags"),
            }
        )
        if len(out) >= limit:
            break
    return out
