"""Daily inventory simulation (raw materials with (s,S) replenishment, finished goods with shipments).

Shared by the history generator and the live simulator (state is JSON-serialisable).
SIMULATED: a stock shortfall is assumed to be covered by an emergency purchase, so physical
stock is clamped at zero while the day's true usage is still recorded.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from app.sim.engine import MATERIALS, PRODUCT_DEFS, SimConfig

FG_DEMAND_RATIO = {"GB-200": 0.55}   # story: over-production of GB-200 -> slow-moving finished goods
DEFAULT_FG_RATIO = 1.0
FG_TARGET_COVER_DAYS = 4.0           # finished goods ship faster when stock is high (mean reversion), except slow movers
FG_FEEDBACK = 0.08
LEAD_DAYS = 3
STEEL_DISRUPTION_WINDOW = (52, 58)   # orders placed in this day-index window arrive late
STEEL_DISRUPTION_DELAY = 6


def derive_params(daily_rm_usage: dict[date, dict[str, float]], daily_good: dict[date, dict[str, float]], n_days: int) -> dict[str, dict[str, Any]]:
    """Reorder points / max levels derived from average daily flows of the generated history."""
    params: dict[str, dict[str, Any]] = {}
    for code, m in MATERIALS.items():
        total = sum(d.get(code, 0.0) for d in daily_rm_usage.values())
        avg = total / max(n_days, 1)
        rop = avg * 2.0                         # published reorder point (minimum stock)
        mx = rop + avg * 10                     # target maximum
        params[code] = {"name": m["name"], "type": "raw_material", "unit": "kg", "unit_cost": m["unit_cost"], "sku": None,
                        "avg": avg, "rop": round(rop, 1), "trigger": round(rop + avg * 4.0, 1), "max": round(mx, 1), "init": round(mx * 0.8, 1), "fb": 0.0}
    for p in PRODUCT_DEFS:
        total = sum(d.get(p["sku"], 0.0) for d in daily_good.values())
        avg_prod = total / max(n_days, 1)
        demand = avg_prod * FG_DEMAND_RATIO.get(p["sku"], DEFAULT_FG_RATIO)
        unit_cost = p["bom"] * MATERIALS[p["material"]]["unit_cost"] + p["conv"]
        slow = p["sku"] in FG_DEMAND_RATIO
        params[p["sku"]] = {"name": p["name"], "type": "finished_good", "unit": "units", "unit_cost": round(unit_cost, 2), "sku": p["sku"],
                            "avg": demand, "rop": round(demand * 1.0, 1), "trigger": 0.0, "max": round(demand * 8, 1), "init": round(demand * FG_TARGET_COVER_DAYS, 1),
                            "fb": 0.0 if slow else FG_FEEDBACK}
    return params


class InventorySim:
    def __init__(self, params: dict[str, dict[str, Any]], seed: int, cfg: SimConfig, state: dict | None = None):
        self.params = params
        self.seed = seed
        self.cfg = cfg
        st = state or {}
        self.qty: dict[str, float] = st.get("qty") or {c: float(p["init"]) for c, p in params.items()}
        self.pipeline: list[dict] = list(st.get("pipeline") or [])

    def to_json(self) -> dict:
        return {"qty": self.qty, "pipeline": self.pipeline}

    def _delay(self, code: str, d: date) -> int:
        di = (d - self.cfg.start_date).days
        if code == "MAT-STEEL-SHEET" and STEEL_DISRUPTION_WINDOW[0] <= di <= STEEL_DISRUPTION_WINDOW[1]:
            return STEEL_DISRUPTION_DELAY
        return 0

    def close_day(self, d: date, rm_usage: dict[str, float], good_by_sku: dict[str, float]) -> list[dict]:
        out: list[dict] = []
        for i, (code, p) in enumerate(self.params.items()):
            qty = self.qty[code]
            if p["type"] == "raw_material":
                due = [o for o in self.pipeline if o["code"] == code and date.fromisoformat(o["arrival"]) <= d]
                self.pipeline = [o for o in self.pipeline if o not in due]
                qty += sum(o["qty"] for o in due)
                use = float(rm_usage.get(code, 0.0))
                qty = max(0.0, qty - use)
                on_order = sum(o["qty"] for o in self.pipeline if o["code"] == code)
                if qty + on_order <= p["trigger"]:
                    order = p["max"] - qty - on_order
                    if order > 0:
                        arrival = d + timedelta(days=LEAD_DAYS + self._delay(code, d))
                        self.pipeline.append({"code": code, "arrival": arrival.isoformat(), "qty": round(order, 1)})
            else:
                qty += float(good_by_sku.get(p["sku"], 0.0))
                rng = np.random.default_rng([self.seed, d.toordinal(), i])
                cover = qty / p["avg"] if p["avg"] > 0 else 0.0
                fb = float(np.clip(1.0 + p.get("fb", 0.0) * (cover - FG_TARGET_COVER_DAYS), 0.6, 1.6))
                ship = 0.0 if d.weekday() == 6 else p["avg"] * 7.0 / 6.0 * fb * float(np.exp(rng.normal(0, 0.2)))
                use = float(min(qty, round(ship)))
                qty -= use
            self.qty[code] = qty
            out.append({"snapshot_date": d, "item_code": code, "item_name": p["name"], "item_type": p["type"], "sku": p["sku"], "qty_on_hand": round(qty, 3),
                        "unit": p["unit"], "unit_cost": p["unit_cost"], "reorder_point": p["rop"], "max_level": p["max"], "daily_usage": round(use, 3)})
        return out
