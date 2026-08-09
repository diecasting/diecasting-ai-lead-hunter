"""Quotation cost estimator (Phase 12.2).

Deterministic-first cost rollup. The LLM (``app.ai_sales_agent.llm.complete_json``)
may *only* suggest a gross margin percentage, a price range and a short
explanation; it can never alter the deterministic cost lines. Every returned
line carries the ``cost_rate_id`` it was derived from (when a matching rate
exists in the price book) for full audit traceability.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.ai_sales_agent.llm import complete_json
from app.quotation.fx import convert


QUOTE_CURRENCY_DEFAULT = "USD"
DEFAULT_MARGIN_PCT = 25.0

# Deterministic process assumptions (hours per part). The price book supplies
# the *rates*; these are the simple physics defaults. Swap for real cycle data
# when available — they never come from the LLM.
DIE_CAST_CYCLE_HOURS = 0.02
CNC_HOURS_PER_PART = 0.1

LINE_MATERIAL = "material"
LINE_DIE_CAST_MACHINE = "die_cast_machine"
LINE_CNC = "cnc"
LINE_TOOLING = "tooling"
LINE_FINISHING = "finishing"
LINE_OVERHEAD = "overhead"


@dataclass
class RequirementLike:
    """Duck-typed requirement for inline / API estimates (no DB row)."""

    weight: Optional[float] = None
    material: Optional[str] = None
    process: Optional[str] = None
    annual_volume: Optional[int] = None
    tolerance: Optional[str] = None
    finishing: Optional[str] = None
    complexity: Optional[str] = None


def _norm(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def pick_rate(rates, category: str, code: Optional[str]):
    """Return the best matching CostRate for ``(category, code)``.

    Prefers ``is_default`` rows, then the earliest ``effective_from``; falls
    back to the first match. Returns ``None`` when nothing matches.
    """
    if not rates or not code:
        return None
    cat = (category or "").lower()
    cde = _norm(code)
    matches = [
        r for r in rates
        if (r.category or "").lower() == cat and _norm(r.code) == cde
    ]
    if not matches:
        return None
    defaults = [r for r in matches if r.is_default]
    pool = defaults or matches
    effective = [r for r in pool if r.effective_from is not None]
    if effective:
        return min(effective, key=lambda r: r.effective_from)
    return pool[0]


def match_capability(requirement, capabilities) -> Optional[bool]:
    """Whether OUR factory can make this requirement (capability match).

    Returns ``None`` when no capability data exists (unknown), otherwise True /
    False. Material must appear in the capability's compatibility list and the
    part weight must be within ``max_part_weight``.
    """
    if not capabilities:
        return None
    mat = _norm(requirement.material) if requirement.material else None
    wt = requirement.weight
    for cap in capabilities:
        if not cap.active:
            continue
        comp = _norm(cap.material_compatibility or "")
        parts = [c.strip() for c in comp.split(",") if c.strip()]
        if mat and mat not in parts:
            continue
        if (
            wt is not None
            and cap.max_part_weight is not None
            and wt > cap.max_part_weight
        ):
            continue
        return True
    return False


def _line(line_type, description, quantity, unit, unit_rate, cost_rate_id, amount, used_ai=False):
    return {
        "line_type": line_type,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "unit_rate": unit_rate,
        "cost_rate_id": cost_rate_id,
        "amount": round(amount, 4) if amount is not None else None,
        "used_ai": used_ai,
    }


def estimate_quote(
    requirement,
    capabilities=None,
    rates=None,
    *,
    currency: str = QUOTE_CURRENCY_DEFAULT,
    margin_pct: float = DEFAULT_MARGIN_PCT,
    use_ai: bool = False,
) -> Dict[str, Any]:
    """Deterministic cost rollup (+ optional AI margin/price/explanation).

    Returns a structured estimate dict. Cost lines are always computed
    deterministically from ``requirement`` + ``rates``; the LLM, when enabled,
    may only adjust ``margin_pct`` / ``suggested_price`` and add an explanation.
    """
    rates = rates or []
    capabilities = capabilities or []
    quantity = requirement.annual_volume if requirement.annual_volume else 1
    weight = requirement.weight or 0.0
    mat_code = _norm(requirement.material) if requirement.material else None
    finishing_code = _norm(requirement.finishing) if requirement.finishing else None
    process = (requirement.process or "").lower()

    lines: List[Dict[str, Any]] = []
    total_material = total_machine = total_cnc = total_tooling = total_finishing = 0.0

    # Material
    if weight > 0 and mat_code:
        mat_rate = pick_rate(rates, "material", mat_code)
        if mat_rate is not None:
            amt = convert(
                weight * (mat_rate.rate or 0.0) * quantity,
                mat_rate.currency,
                currency,
            )
            total_material = amt
            lines.append(
                _line(
                    LINE_MATERIAL,
                    f"Material ({requirement.material})",
                    quantity,
                    mat_rate.unit or "kg",
                    mat_rate.rate,
                    mat_rate.id,
                    amt,
                )
            )

    # Die casting machine
    if "cast" in process:
        dc_rate = pick_rate(rates, "machine_hour", "dc_machine")
        if dc_rate is not None:
            hrs = quantity * DIE_CAST_CYCLE_HOURS
            amt = convert(hrs * (dc_rate.rate or 0.0), dc_rate.currency, currency)
            total_machine = amt
            lines.append(
                _line(
                    LINE_DIE_CAST_MACHINE,
                    "Die casting machine",
                    hrs,
                    dc_rate.unit or "hour",
                    dc_rate.rate,
                    dc_rate.id,
                    amt,
                )
            )

    # CNC machining
    if "cnc" in process or "machin" in process:
        cnc_rate = pick_rate(rates, "machine_hour", "cnc_machine")
        if cnc_rate is not None:
            hrs = quantity * CNC_HOURS_PER_PART
            amt = convert(hrs * (cnc_rate.rate or 0.0), cnc_rate.currency, currency)
            total_cnc = amt
            lines.append(
                _line(
                    LINE_CNC,
                    "CNC machining",
                    hrs,
                    cnc_rate.unit or "hour",
                    cnc_rate.rate,
                    cnc_rate.id,
                    amt,
                )
            )

    # Tooling / mold (one-time) — applicable for casting or unspecified process
    if ("cast" in process) or (not process):
        tool_rate = pick_rate(rates, "tooling", "mold")
        if tool_rate is not None:
            amt = convert(tool_rate.rate or 0.0, tool_rate.currency, currency)
            total_tooling = amt
            lines.append(
                _line(
                    LINE_TOOLING,
                    "Tooling / mold (amortized)",
                    1.0,
                    tool_rate.unit or "lot",
                    tool_rate.rate,
                    tool_rate.id,
                    amt,
                )
            )

    # Finishing
    if finishing_code:
        fin_rate = pick_rate(rates, "finishing", finishing_code)
        if fin_rate is not None:
            amt = convert(
                quantity * (fin_rate.rate or 0.0), fin_rate.currency, currency
            )
            total_finishing = amt
            lines.append(
                _line(
                    LINE_FINISHING,
                    f"Finishing ({requirement.finishing})",
                    quantity,
                    fin_rate.unit or "piece",
                    fin_rate.rate,
                    fin_rate.id,
                    amt,
                )
            )

    # Overhead (always; pct of subtotal when unit == pct)
    subtotal = (
        total_material + total_machine + total_cnc + total_tooling + total_finishing
    )
    total_overhead = 0.0
    overhead_rate = pick_rate(rates, "overhead", "factory")
    if overhead_rate is not None:
        if (overhead_rate.unit or "").lower() == "pct":
            total_overhead = subtotal * (overhead_rate.rate or 0.0) / 100.0
        else:
            total_overhead = overhead_rate.rate or 0.0
        total_overhead = convert(total_overhead, overhead_rate.currency, currency)
        lines.append(
            _line(
                LINE_OVERHEAD,
                "Factory overhead",
                None,
                overhead_rate.unit or "pct",
                overhead_rate.rate,
                overhead_rate.id,
                total_overhead,
            )
        )

    total_cost = subtotal + total_overhead

    margin_pct = margin_pct if margin_pct is not None else DEFAULT_MARGIN_PCT
    if 0 < margin_pct < 100:
        suggested_price = total_cost / (1 - margin_pct / 100.0)
    else:
        suggested_price = total_cost
    margin_amount = suggested_price - total_cost

    feasible = match_capability(requirement, capabilities)

    estimate: Dict[str, Any] = {
        "lines": lines,
        "total_material_cost": round(total_material, 4),
        "total_machine_cost": round(total_machine, 4),
        "total_cnc_cost": round(total_cnc, 4),
        "total_tooling_cost": round(total_tooling, 4),
        "total_finishing_cost": round(total_finishing, 4),
        "subtotal": round(subtotal, 4),
        "total_overhead": round(total_overhead, 4),
        "total_cost": round(total_cost, 4),
        "suggested_price": round(suggested_price, 4),
        "margin_pct": margin_pct,
        "margin_amount": round(margin_amount, 4),
        "currency": currency,
        "used_ai": False,
        "explanation": "",
        "feasible": feasible,
        "price_range": None,
    }

    used_ai = False
    if use_ai:
        estimate, used_ai = enhance_with_ai(requirement, estimate)
    estimate["used_ai"] = used_ai
    return estimate


def enhance_with_ai(requirement, base: Dict[str, Any]):
    """LLM may suggest margin_pct / price range / explanation only.

    Never modifies the deterministic cost lines. Returns ``(estimate, used_ai)``.
    """
    ai = complete_json(
        system=(
            "You are a manufacturing quotation assistant. Given a product "
            "requirement and a deterministic cost estimate, you may suggest a "
            "gross margin percentage (0-80), an indicative price range, and a "
            "short explanation. Return JSON with exactly these keys: "
            "margin_pct (number), price_min (number), price_max (number), "
            "explanation (string). Do not change the cost."
        ),
        user=(
            f"requirement: material={requirement.material}, "
            f"process={requirement.process}, weight={requirement.weight}, "
            f"annual_volume={requirement.annual_volume}, "
            f"finishing={requirement.finishing}. "
            f"deterministic total_cost={base['total_cost']} {base['currency']}."
        ),
        temperature=0.2,
        max_tokens=400,
    )
    if not isinstance(ai, dict):
        return base, False

    contributed = False
    margin = ai.get("margin_pct")
    if isinstance(margin, (int, float)) and 0 < float(margin) < 100:
        margin = float(margin)
        base = {**base, "margin_pct": margin}
        tc = base["total_cost"]
        sp = tc / (1 - margin / 100.0) if margin < 100 else tc
        base["suggested_price"] = round(sp, 4)
        base["margin_amount"] = round(sp - tc, 4)
        contributed = True

    expl = (ai.get("explanation") or "").strip()
    if expl:
        base = {**base, "explanation": expl}
        contributed = True

    price_min = ai.get("price_min")
    price_max = ai.get("price_max")
    if price_min is not None or price_max is not None:
        base["price_range"] = [price_min, price_max]

    if contributed:
        base = {**base, "used_ai": True}
    return base, contributed
