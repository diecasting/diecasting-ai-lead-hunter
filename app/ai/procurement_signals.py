"""Industrial procurement-signal analysis (Phase 3 Stage 2).

Extends the Phase 2.3 rule engine with explicit *procurement* signals that
indicate a company is actively buying die-casting / CNC / manufacturing services
(versus merely describing what it makes): casting demand, CNC demand, OEM
engagement, supplier posture, and manufacturing capability.

The scoring is deterministic and transparent (no LLM). Each signal returns a
0–100 score plus the matched phrases so the reason text stays explainable.
"""
from typing import Dict, List, Tuple

# (needle, weight) — each contributes once even on multiple matches (capped 100).
CASTING_SIGNALS: List[Tuple[str, int]] = [
    ("die casting", 30),
    ("die-casting", 30),
    ("high pressure die casting", 25),
    ("hpdc", 20),
    ("aluminium die casting", 25),
    ("aluminum die casting", 25),
    ("magnesium die casting", 20),
    ("zinc die casting", 15),
    ("gravity die casting", 15),
    ("casting supplier", 20),
    ("casting manufacturer", 20),
    ("casting company", 15),
    ("casting service", 15),
    ("die caster", 20),
    ("die cast part", 15),
    ("casting parts", 15),
    ("casting components", 15),
    ("casting capabilities", 15),
    ("casting facility", 10),
    ("tolerance casting", 10),
]

CNC_SIGNALS: List[Tuple[str, int]] = [
    ("cnc machining", 30),
    ("cnc", 20),
    ("5-axis machining", 25),
    ("5 axis machining", 25),
    ("precision machining", 20),
    ("cnc milling", 20),
    ("cnc turning", 20),
    ("cnc machining services", 20),
    ("machining supplier", 15),
    ("machining company", 15),
    ("machining capabilities", 15),
    ("cnc service", 15),
    ("cnc shop", 15),
    ("machined parts", 15),
    ("precision components", 15),
    ("precision parts", 15),
]

OEM_SIGNALS: List[Tuple[str, int]] = [
    ("oem", 25),
    ("original equipment manufacturer", 25),
    ("oem partner", 20),
    ("oem supplier", 20),
    ("oem service", 15),
    ("tier 1", 20),
    ("tier 1 supplier", 20),
    ("tier 2", 15),
    ("automotive oem", 20),
    ("oem approved", 15),
    ("oem manufacturer", 15),
    ("sub-assembly", 10),
    ("assembly service", 10),
    ("contract manufacturing", 15),
    ("private label", 10),
    ("white label", 10),
]

SUPPLIER_SIGNALS: List[Tuple[str, int]] = [
    ("supplier", 20),
    ("component supplier", 15),
    ("global supplier", 15),
    ("reliable supplier", 10),
    ("certified supplier", 15),
    ("preferred supplier", 15),
    ("supply chain", 15),
    ("sourcing", 15),
    ("procurement", 20),
    ("purchase", 10),
    ("purchasing", 15),
    ("rfq", 15),
    ("request for quote", 15),
    ("quote request", 15),
    ("distributor", 10),
    ("wholesale", 10),
    ("export", 10),
    ("exporter", 10),
]

MANUFACTURING_CAPABILITY_SIGNALS: List[Tuple[str, int]] = [
    ("manufacturing capability", 15),
    ("manufacturing capabilities", 15),
    ("manufacturing facility", 10),
    ("manufacturing plant", 10),
    ("production line", 10),
    ("production capacity", 15),
    ("tonnage", 15),
    ("clamping force", 15),
    ("shot weight", 10),
    ("cavity", 10),
    ("tool room", 15),
    ("tool shop", 15),
    ("in-house", 15),
    ("inhouse", 15),
    ("iso 9001", 10),
    ("iatf 16949", 15),
    ("quality management", 10),
    ("inspection", 10),
    ("cm", 10),
    ("cmm", 10),
    ("secondary operations", 10),
    ("surface treatment", 10),
    ("powder coating", 10),
    ("anodizing", 10),
    (" painting", 5),
]


def _score(text: str, rules: List[Tuple[str, int]]) -> Tuple[int, List[str]]:
    lowered = (text or "").lower()
    matched: List[str] = []
    score = 0
    for needle, weight in rules:
        if needle in lowered and needle not in matched:
            matched.append(needle)
            score += weight
    return max(0, min(100, score)), matched


def casting_signal_score(text: str) -> Tuple[int, List[str]]:
    return _score(text, CASTING_SIGNALS)


def cnc_signal_score(text: str) -> Tuple[int, List[str]]:
    return _score(text, CNC_SIGNALS)


def oem_signal_score(text: str) -> Tuple[int, List[str]]:
    return _score(text, OEM_SIGNALS)


def supplier_signal_score(text: str) -> Tuple[int, List[str]]:
    return _score(text, SUPPLIER_SIGNALS)


def manufacturing_capability_score(text: str) -> Tuple[int, List[str]]:
    return _score(text, MANUFACTURING_CAPABILITY_SIGNALS)


def analyze_procurement_signals(text: str) -> Dict:
    """Return a structured procurement-signal report for ``text``.

    Keys: casting / cnc / oem / supplier / manufacturing_capability, each a dict
    with ``score`` (0–100) and ``matched`` (list of phrases). Plus an overall
    ``procurement_score`` (max of the five) and the dominant ``procurement_type``.
    """
    casting_s, casting_m = casting_signal_score(text)
    cnc_s, cnc_m = cnc_signal_score(text)
    oem_s, oem_m = oem_signal_score(text)
    supplier_s, supplier_m = supplier_signal_score(text)
    mfg_s, mfg_m = manufacturing_capability_score(text)

    components = {
        "casting": {"score": casting_s, "matched": casting_m},
        "cnc": {"score": cnc_s, "matched": cnc_m},
        "oem": {"score": oem_s, "matched": oem_m},
        "supplier": {"score": supplier_s, "matched": supplier_m},
        "manufacturing_capability": {"score": mfg_s, "matched": mfg_m},
    }

    # Overall procurement appetite = strongest single signal.
    procurement_score = max(casting_s, cnc_s, oem_s, supplier_s, mfg_s)
    procurement_type = max(components, key=lambda k: components[k]["score"])

    return {
        "components": components,
        "procurement_score": procurement_score,
        "procurement_type": procurement_type,
    }
