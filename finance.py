"""Scalar, Decimal-based reference implementation of the per-record loss model.

The dashboard uses a vectorised pandas version for speed (analytics.py); tests assert both agree.
`money()` is used at every aggregation boundary so published figures are exact to 2 decimal places.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..config import Settings

D = Decimal
CENT = D("0.01")


def d(x: Any) -> Decimal:
    return x if isinstance(x, Decimal) else D(str(x))


def money(x: Any) -> float:
    """Round half-up to 2 dp using Decimal; NaN/None -> 0.0."""
    if x is None or (isinstance(x, float) and x != x):
        return 0.0
    return float(d(x).quantize(CENT, rounding=ROUND_HALF_UP))


def safe_div(a: Any, b: Any) -> float | None:
    b = d(b)
    return None if b == 0 else float(d(a) / b)


def record_losses(row: dict, cfg: Settings, base_kwh_per_unit: float | None) -> dict[str, Decimal]:
    """Observed loss per category for one production record.

    row keys: unpl_down, ideal_rate, unit_price, std_mat, std_conv, defective, units, kwh, tariff, material_cost
    """
    cm_unit = d(row["unit_price"]) - d(row["std_mat"]) - d(row["std_conv"])
    lost_units = d(row["unpl_down"]) / 60 * d(row["ideal_rate"])
    downtime = lost_units * cm_unit * d(cfg.downtime_unrecoverable_share)
    quality = d(row["defective"]) * (d(row["std_mat"]) + d(row["std_conv"])) * (1 - d(cfg.scrap_salvage_rate))
    energy = D(0)
    if base_kwh_per_unit is not None and row["units"] > 0:
        allowed = d(base_kwh_per_unit) * d(row["units"]) * (1 + d(cfg.energy_tolerance_pct) / 100)
        energy = max(D(0), d(row["kwh"]) - allowed) * d(row["tariff"])
    allowed_mat = d(row["units"]) * d(row["std_mat"]) * (1 + d(cfg.material_allowance_pct) / 100)
    material = max(D(0), d(row["material_cost"]) - allowed_mat)
    return {"downtime": downtime, "quality": quality, "energy": energy, "material": material}


def savings_from_rates(baseline_rate: float, post_rate: float, post_volume: float) -> Decimal:
    """(baseline cost rate - post cost rate) x post-intervention driver volume."""
    return (d(baseline_rate) - d(post_rate)) * d(post_volume)
