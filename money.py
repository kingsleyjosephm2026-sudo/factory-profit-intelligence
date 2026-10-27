"""Small, dependency-free helpers for safe arithmetic and money handling.

Design note on precision: row-level analytics run in float64 (vectorised pandas). float64 carries
~15 significant digits, so even a 1e9 currency total is accurate to ~1e-6. Every *reported* money
value, and every scalar business formula (savings verification, carrying cost, contribution
margin), is computed or finalised with `decimal.Decimal` and quantised to 2 dp (ROUND_HALF_UP).
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")


def D(x: Any) -> Decimal:
    """Convert to Decimal without binary-float artefacts. None/NaN/inf -> Decimal(0)."""
    if x is None:
        return Decimal(0)
    if isinstance(x, Decimal):
        return x
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return Decimal(0)
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def q2(x: Any) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def money(x: Any) -> float:
    """Quantised money as a JSON-friendly float."""
    return float(q2(x))


def num(x: Any, ndigits: int = 3) -> float | None:
    """Plain number for JSON: None for None/NaN/inf."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, ndigits)


def safe_div(a: Any, b: Any) -> float | None:
    """a / b, or None when b is zero/None/NaN (never raises, never returns inf)."""
    try:
        if a is None or b is None:
            return None
        fb = float(b)
        fa = float(a)
        if fb == 0 or math.isnan(fb) or math.isnan(fa):
            return None
        return fa / fb
    except (TypeError, ValueError):
        return None


def pct(a: Any, b: Any) -> float | None:
    r = safe_div(a, b)
    return None if r is None else r * 100.0


def pct_change(current: Any, previous: Any) -> float | None:
    """Percentage difference vs the previous period; None when mathematically invalid (previous = 0)."""
    if current is None or previous is None:
        return None
    try:
        prev = float(previous)
        cur = float(current)
    except (TypeError, ValueError):
        return None
    if prev == 0 or math.isnan(prev) or math.isnan(cur):
        return None
    return (cur - prev) / abs(prev) * 100.0


def compare(current: Any, previous: Any, ndigits: int = 2) -> dict[str, float | None]:
    cur = None if current is None else float(current)
    prev = None if previous is None else float(previous)
    diff = None if cur is None or prev is None else cur - prev
    return {
        "current": num(cur, ndigits),
        "previous": num(prev, ndigits),
        "abs_diff": num(diff, ndigits),
        "pct_diff": num(pct_change(cur, prev), 2),
    }


def contribution_margin_per_unit(price: Any, bom_kg: Any, material_cost_per_kg: Any, conversion_cost: Any) -> Decimal:
    """CM per unit = selling price - material cost - variable conversion cost."""
    return q2(D(price) - D(bom_kg) * D(material_cost_per_kg) - D(conversion_cost))


def carrying_cost(inventory_value: Any, annual_rate_pct: Any, days: Any = 1) -> Decimal:
    """Inventory carrying cost = value x annual rate x days / 365."""
    return q2(D(inventory_value) * D(annual_rate_pct) / Decimal(100) * D(days) / Decimal(365))


def energy_cost(kwh: Any, tariff_per_kwh: Any) -> Decimal:
    return q2(D(kwh) * D(tariff_per_kwh))
