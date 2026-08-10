"""Phase 16.2: multilingual industrial die-casting RFQ keyword dictionary.

This module is the **deterministic** phrase bank used by the RFQ keyword
extractor adapter (see :mod:`app.intent.extractors`). It complements the
English-only :data:`app.ai.keywords.BUYING_SIGNALS` bank used by the website
extractor and adds **German (DE)** coverage so German-language prospect sites
and RFQ portals are detected with the same precision.

Design rules (strictly deterministic — no LLM, no network):

* Matching is case-insensitive **substring** matching against concatenated
  text, exactly like :func:`app.ai.scoring.detect_buying_signal`, so the two
  detectors behave consistently. Keep phrases lower-case and avoid regex
  meta-characters.
* Three intent tiers exactly mirror ``BUYING_SIGNALS``:
  - ``HIGH``   — explicit RFQ / procurement / supplier-sourcing language.
  - ``MEDIUM`` — die-casting capability / supplier-of interest language.
  - ``LOW``    — middleman language (distributor / trader / wholesale); these
                 are *negative* buying-intent for our capacity and map to a
                 deterrent signal value in the extractor.
* :func:`scan_keywords` returns the same shape as
  :func:`app.ai.scoring.detect_buying_signal`
  (``{"level": ..., "matched": [...], "detail": ...}``) so adapters can treat
  both detectors interchangeably.

Languages: ``EN`` (English) and ``DE`` (German). ``lang="AUTO"`` scans both
and merges the result (highest tier wins; phrases are de-duplicated so a
substring of an already-matched longer phrase is not double-counted).
"""
from typing import Dict, List

# Languages this dictionary supports.
SUPPORTED_LANGUAGES: tuple = ("EN", "DE")

# ---------------------------------------------------------------------------
# Multilingual RFQ / procurement phrase bank
# ---------------------------------------------------------------------------
# Structure: RFQ_KEYWORDS[lang][tier] = [phrase, ...]
# Phrases are lower-case; matching is case-insensitive substring.
RFQ_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    # --- English -------------------------------------------------------------
    "EN": {
        # Explicit request for quotation / sourcing / contract manufacturing.
        "HIGH": [
            "request for quotation",
            "request for quote",
            "request a quote",
            "quote request",
            "quotation request",
            "get a quote",
            "send us your quote",
            "submit a quote",
            "rfq",
            "rfp",
            "price request",
            "looking for suppliers",
            "looking for a supplier",
            "supplier wanted",
            "suppliers wanted",
            "open tender",
            "invitation to tender",
            "call for quotes",
            "sourcing",
            "oem partner",
            "contract manufacturing",
            "procurement",
            "purchase order",
        ],
        # Capability / supplier-of interest (implicit intent).
        "MEDIUM": [
            "die casting",
            "aluminium die casting",
            "aluminum die casting",
            "pressure die casting",
            "cnc machining",
            "custom parts",
            "precision components",
            "precision parts",
            "manufacturer",
            "production capability",
            "supplier of",
            "made to order",
            "tooling",
            "prototypes",
            "prototype",
            "casting supplier",
            "machining supplier",
            "series production",
        ],
        # Middleman language — not a direct buyer of our capacity.
        "LOW": [
            "distributor",
            "trader",
            "wholesale",
            "reseller",
            "trading company",
            "broker",
        ],
    },
    # --- German (Deutsch) ----------------------------------------------------
    "DE": {
        # Explicit Anfrage / Ausschreibung / Beschaffung.
        "HIGH": [
            "angebotsanfrage",
            "preisanfrage",
            "lieferantenanfrage",
            "anfrage",
            "bitte um angebot",
            "offene ausschreibung",
            "ausschreibung",
            "lieferant gesucht",
            "lieferanten gesucht",
            "fertigungspartner",
            "vertragsfertigung",
            "beschaffung",
            "preisanfrage für",
            "anfrage für",
        ],
        # Druckguss-Fähigkeit / Lieferanten-Interesse (implizit).
        "MEDIUM": [
            "druckguss",
            "aluminiumdruckguss",
            "druckguss-teile",
            "druckgussteile",
            "cnc-bearbeitung",
            "präzisionsteile",
            "kundenspezifische teile",
            "hersteller",
            "produktionskapazität",
            "lieferant von",
            "werkzeugbau",
            "prototypen",
            "druckgusslieferant",
            "serienfertigung",
        ],
        # Zwischenhändler-Sprache.
        "LOW": [
            "distributor",
            "großhandel",
            "wiederverkäufer",
            "handelsunternehmen",
            "händler",
        ],
    },
}

# Tier evaluation order (highest intent wins).
_TIERS = ("HIGH", "MEDIUM", "LOW")


def _scan_one(text_lower: str, lang_dict: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Scan ``text_lower`` against one language's phrase bank.

    Returns ``{"HIGH": [...], "MEDIUM": [...], "LOW": [...]}`` with phrases
    de-duplicated so a shorter phrase that is a substring of an already-matched
    longer phrase is skipped (e.g. ``"anfrage"`` inside ``"angebotsanfrage"``).
    """
    matched: Dict[str, List[str]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for tier in _TIERS:
        # Longest phrases first so they claim their substrings.
        for phrase in sorted(lang_dict.get(tier, []), key=len, reverse=True):
            if phrase in text_lower:
                # Skip if a longer already-matched phrase already covers it.
                if any(phrase in m for m in matched[tier]):
                    continue
                matched[tier].append(phrase)
    return matched


def scan_keywords(text: str, lang: str = "EN") -> Dict[str, object]:
    """Deterministic multilingual RFQ / buying-intent scan.

    Parameters
    ----------
    text:
        Concatenated prospect text (website, RFQ portal snippet, ...).
    lang:
        ``"EN"``, ``"DE"``, or ``"AUTO"``. ``"AUTO"`` scans both languages and
        merges (highest tier wins; phrases de-duplicated across languages).

    Returns
    -------
    dict
        ``{"level": "HIGH"|"MEDIUM"|"LOW"|"NONE", "matched": [...], "detail": str}``
        — the same shape as :func:`app.ai.scoring.detect_buying_signal`.
    """
    lowered = (text or "").lower()
    lang = (lang or "EN").upper()

    if lang == "AUTO":
        langs = [l for l in SUPPORTED_LANGUAGES if l in RFQ_KEYWORDS]
    elif lang in RFQ_KEYWORDS:
        langs = [lang]
    else:
        # Unknown language code -> fall back to English only (deterministic).
        langs = ["EN"]

    combined: Dict[str, List[str]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for l in langs:
        one = _scan_one(lowered, RFQ_KEYWORDS[l])
        for tier in _TIERS:
            for phrase in one[tier]:
                if phrase not in combined[tier]:
                    combined[tier].append(phrase)

    if combined["HIGH"]:
        level = "HIGH"
    elif combined["MEDIUM"]:
        level = "MEDIUM"
    elif combined["LOW"]:
        level = "LOW"
    else:
        level = "NONE"

    all_matched = combined["HIGH"] + combined["MEDIUM"] + combined["LOW"]
    detail = "; ".join(all_matched) if all_matched else "no explicit rfq signal"
    return {"level": level, "matched": all_matched, "detail": detail}
