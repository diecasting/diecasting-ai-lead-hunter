"""Keyword library for the production lead-generation pipeline.

The pipeline reads this library each scheduled run. Two sources are supported,
in priority order:

1. A plain-text file (one keyword per line, ``#`` for comments) at the path
   given by ``settings.keywords_file`` (default ``data/keywords.txt``).
2. A built-in :data:`DEFAULT_KEYWORDS` list, used as a fallback.
"""
import os
from typing import List

DEFAULT_KEYWORDS: List[str] = [
    "aluminum die casting supplier",
    "magnesium die casting manufacturer",
    "EV motor housing manufacturer",
    "CNC precision machining supplier",
    "zinc die casting company",
    "automotive die casting OEM",
    "high pressure die casting manufacturer",
    "die casting mold maker",
    "die casting parts supplier",
    "aluminum investment casting manufacturer",
    "pressure die casting factory",
    "tolerances precision CNC machining OEM",
]


def load_keywords(path: str = None) -> List[str]:
    """Load keywords from ``path`` (or ``settings.keywords_file``).

    Falls back to :data:`DEFAULT_KEYWORDS` when the file is missing.
    """
    target = path or os.environ.get("KEYWORDS_FILE") or None
    if target and os.path.exists(target):
        keywords: List[str] = []
        with open(target, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    keywords.append(line)
        if keywords:
            return keywords
    return list(DEFAULT_KEYWORDS)
