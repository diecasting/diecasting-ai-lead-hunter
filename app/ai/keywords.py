"""Industrial keyword library for die-casting lead intelligence (Phase 2.3).

These vocabulary banks drive every downstream detector in ``app.ai``:

* ``MATERIALS``   — metals / alloys a die-casting buyer specifies.
* ``PROCESSES``   — manufacturing processes relevant to our sales motion.
* ``INDUSTRIES``  — downstream markets that consume cast / machined parts.
* ``BUYING_SIGNALS`` — phrase banks that reveal purchase intent (HIGH / MEDIUM / LOW).

All matching is done case-insensitively against concatenated website text, so
keep the strings lower-case and avoid regex meta-characters.
"""
from typing import Dict, List

# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
MATERIALS: List[str] = [
    "aluminum",
    "aluminium",
    "adc12",
    "a380",
    "6061",
    "7075",
    "magnesium",
    "az91",
    # Supporting alloys / families (detected but lighter-weighted in scoring).
    "zinc",
    "zamak",
    "al-si",
]

# ---------------------------------------------------------------------------
# Manufacturing processes
# ---------------------------------------------------------------------------
PROCESSES: List[str] = [
    "die casting",
    "pressure casting",
    "gravity casting",
    "sand casting",
    "investment casting",
    "cnc machining",
    "5 axis machining",
    "precision machining",
    "tooling",
    "mold",
    "mould",
]

# ---------------------------------------------------------------------------
# Downstream industries
# ---------------------------------------------------------------------------
INDUSTRIES: List[str] = [
    "automotive",
    "ev",
    "electric vehicle",
    "battery",
    "motor housing",
    "gearbox",
    "pump",
    "hydraulic",
    "robotics",
    "industrial equipment",
    "aerospace",
]

# ---------------------------------------------------------------------------
# Buying-signal phrase banks (section 3)
# ---------------------------------------------------------------------------
BUYING_SIGNALS: Dict[str, List[str]] = {
    # Strong, active purchase intent.
    "HIGH": [
        "looking for suppliers",
        "new supplier",
        "oem partner",
        "sourcing",
        "contract manufacturing",
        "request for quotation",
        "request for quote",
        "rfq",
        "open tender",
    ],
    # Moderate intent — the company makes / can make, but intent is implicit.
    "MEDIUM": [
        "manufacturer",
        "production capability",
        "custom parts",
        "precision components",
        "capabilities",
        "supplier of",
        "made to order",
    ],
    # Weak / passive — likely a middleman, not a direct buyer of our capacity.
    "LOW": [
        "distributor",
        "trader",
        "wholesale",
        "reseller",
        "trading company",
    ],
}
