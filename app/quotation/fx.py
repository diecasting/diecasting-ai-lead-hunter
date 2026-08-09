"""Minimal offline FX conversion (Phase 12.2).

A small static rate table keyed off USD. This keeps the estimator hermetic and
testable without a live FX feed; a production build would swap this for an
ERP/MES feed or a market-data provider. Rates are indicative and intended for
internal quoting only.
"""
from typing import Optional

# How many USD 1 unit of the currency is worth.
_USD_PER_UNIT = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CNY": 0.14,
    "JPY": 0.0067,
    "CAD": 0.73,
    "AUD": 0.66,
}


def convert(
    amount: Optional[float],
    from_ccy: Optional[str],
    to_ccy: Optional[str],
) -> float:
    """Convert ``amount`` from ``from_ccy`` to ``to_ccy`` (USD-based).

    Returns ``amount`` unchanged when currencies are equal, missing, or unknown
    (a 1:1 fallback for unknown codes rather than a silent bad guess).
    """
    if amount is None:
        return 0.0
    from_ccy = (from_ccy or "").upper()
    to_ccy = (to_ccy or "").upper()
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return float(amount)
    from_rate = _USD_PER_UNIT.get(from_ccy)
    to_rate = _USD_PER_UNIT.get(to_ccy)
    if from_rate is None or to_rate is None:
        return float(amount)
    usd = float(amount) * from_rate
    return usd / to_rate
