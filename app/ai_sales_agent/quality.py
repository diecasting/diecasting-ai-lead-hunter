"""Email quality scoring (Phase 9 AI Sales Agent).

Pure, deterministic scoring of a sales email (subject + body). Returns an
overall 0-100 score plus per-dimension sub-scores and human-readable
suggestions. No network / LLM required, so it is safe to run in tests and on
the hot path of draft generation.

Dimensions (weighted into ``overall``):
  * length           — subject 3-12 words; body 40-450 words
  * personalization  — company name + recipient first name + greeting present
  * cta              — a clear next-step verb and/or a question to prompt reply
  * readability      — average sentence length (< ~25 words is healthy)
  * professionalism  — no hype / spam phrases, no spammy punctuation
  * structure        — greeting + sign-off present
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Hype / spam phrases that hurt deliverability and credibility.
_SPAM_PHRASES = [
    "free", "guaranteed", "100%", "best price", "cheapest", "act now",
    "urgent", "limited time", "click here", "buy now", "discount",
    "no obligation", "risk free", "winner", "congratulations", "best-in-class",
]

# Greeting must start a line (the subject precedes the body when the two are
# concatenated), so we match at line starts via MULTILINE rather than the
# absolute start of the string -- otherwise a real "Dear ..." opening placed
# after the subject would never be detected.
_GREETING_RE = re.compile(r"^\s*(dear|hi|hello|greetings)\b", re.IGNORECASE | re.MULTILINE)
_SIGNOFF_RE = re.compile(
    r"(regards|sincerely|best wishes|thank you|thanks|cheers|respectfully)\b",
    re.IGNORECASE,
)

# Verbs that signal a concrete next step.
_CTA_VERBS = (
    "schedule", "call", "meet", "discuss", "review", "share", "send",
    "connect", "arrange", "explore", "propose", "introduce", "set up",
    "book", "call", "send",
)


@dataclass
class EmailQualityScore:
    overall: int
    length: int
    personalization: int
    cta: int
    readability: int
    professionalism: int
    structure: int
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "overall": self.overall,
            "dimensions": {
                "length": self.length,
                "personalization": self.personalization,
                "cta": self.cta,
                "readability": self.readability,
                "professionalism": self.professionalism,
                "structure": self.structure,
            },
            "suggestions": self.suggestions,
        }


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _avg_sentence_len(text: str) -> float:
    sentences = [s for s in re.split(r"[.!?]+", text or "") if s.strip()]
    if not sentences:
        return 0.0
    return sum(_word_count(s) for s in sentences) / len(sentences)


def score_email(
    subject: str,
    body: str,
    *,
    company: Optional[str] = None,
    to_name: Optional[str] = None,
) -> EmailQualityScore:
    """Score a sales email deterministically. Returns an :class:`EmailQualityScore`."""
    subject = subject or ""
    body = body or ""
    combined = f"{subject}\n{body}"
    lower = combined.lower()
    suggestions: List[str] = []

    # --- Length -------------------------------------------------------------
    length = 100
    subj_words = _word_count(subject)
    body_words = _word_count(body)
    if subj_words == 0:
        length -= 40
        suggestions.append("Add a subject line.")
    elif subj_words > 14:
        length -= 20
        suggestions.append("Subject is long; keep it under ~12 words.")
    elif subj_words < 3:
        length -= 15
        suggestions.append("Subject is very short; add context.")
    if body_words == 0:
        length -= 40
        suggestions.append("Body is empty.")
    elif body_words < 40:
        length -= 20
        suggestions.append("Body is short; aim for 60-250 words.")
    elif body_words > 450:
        length -= 15
        suggestions.append("Body is long; tighten to under ~400 words.")
    length = max(0, min(100, length))

    # --- Personalization ----------------------------------------------------
    personalization = 0
    if company and company.strip().lower() in lower:
        personalization += 50
    else:
        suggestions.append("Reference the prospect company by name.")
    first = (to_name or "").split()[0] if to_name else ""
    if first and first.lower() in body.lower():
        personalization += 30
    else:
        suggestions.append("Address the recipient by first name.")
    if _GREETING_RE.search(combined):
        personalization += 20
    personalization = max(0, min(100, personalization))

    # --- CTA ----------------------------------------------------------------
    cta = 0
    has_verb = any(v in lower for v in _CTA_VERBS)
    has_question = "?" in combined
    if has_verb:
        cta += 60
    else:
        suggestions.append("Include a clear next step (call, meeting, review).")
    if has_question:
        cta += 40
    else:
        suggestions.append("End with a question to prompt a reply.")
    cta = max(0, min(100, cta))

    # --- Readability --------------------------------------------------------
    avg = _avg_sentence_len(body)
    readability = 100
    if avg == 0:
        readability = 0
    elif avg > 28:
        readability = 55
        suggestions.append("Shorten sentences for readability (avg < 25 words).")
    elif avg > 22:
        readability = 80
    readability = max(0, min(100, readability))

    # --- Professionalism ----------------------------------------------------
    professionalism = 100
    found_spam = [p for p in _SPAM_PHRASES if p in lower]
    if found_spam:
        professionalism -= min(60, 15 * len(found_spam))
        suggestions.append(
            "Avoid hype/spam phrases: " + ", ".join(found_spam[:3]) + "."
        )
    if combined.count("!") >= 3:
        professionalism -= 15
        suggestions.append("Too many exclamation marks; tone them down.")
    professionalism = max(0, min(100, professionalism))

    # --- Structure ----------------------------------------------------------
    structure = 0
    if _GREETING_RE.search(combined):
        structure += 50
    else:
        suggestions.append("Open with a greeting (e.g. 'Dear ...').")
    if _SIGNOFF_RE.search(body):
        structure += 50
    else:
        suggestions.append("Close with a sign-off (e.g. 'Best regards').")
    structure = max(0, min(100, structure))

    overall = round(
        0.25 * length
        + 0.25 * personalization
        + 0.20 * cta
        + 0.15 * readability
        + 0.10 * professionalism
        + 0.05 * structure
    )
    overall = max(0, min(100, overall))

    return EmailQualityScore(
        overall=overall,
        length=length,
        personalization=personalization,
        cta=cta,
        readability=readability,
        professionalism=professionalism,
        structure=structure,
        suggestions=suggestions,
    )
