"""Profit-leakage model.

Three tiers per category (never summed into one "recoverable profit" number):

  observed          cost of the effect as measured / calculated from the data
  avoidable         the part above an explicit allowance or baseline (conservative)
  potential savings avoidable x savings_realization_factor (what is realistically recoverable)

Categories use DISJOINT cost components so nothing is counted twice:

  downtime   contribution margin on the good units NOT produced during unplanned stops
             (CM = price - material - variable conversion; material is therefore not counted again)
  quality    conversion cost sunk in scrapped units + rework cost of reworked units (material of
             scrapped units is counted under 'material', lost sales are not counted at all)
  energy     cost of kWh above the machine's fitted baseline (the baseline energy is already in
             the standard conversion cost, so only the excess is a loss)
  material   material in scrapped units + process waste above BOM x units
  inventory  carrying cost of stock on hand (avoidable = stock above the target maximum)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.analytics.money import money, num, q2

CATEGORIES: list[tuple[str, str]] = [
    ("downtime", "Downtime impact"),
    ("quality", "Quality-related costs"),
    ("energy", "Excess energy consumption"),
    ("material", "Material waste"),
    ("inventory", "Inventory carrying costs"),
]
ROW_CATEGORIES = ["downtime", "quality", "energy", "material"]
ENERGY_BASELINE_DAYS = 28


def _ratio(num_: pd.Series, den: pd.Series) -> pd.Series:
    out = np.where(den > 0, num_ / den.where(den > 0, 1), 0.0)
    return pd.Series(np.clip(out, 0.0, 1.0), index=num_.index)


def compute_loss_rows(fact: pd.DataFrame, A: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    df = fact.copy()
    cols = [f"{c}_{t}" for c in ROW_CATEGORIES for t in ("observed", "avoidable")]
    if df.empty:
        for c in cols + ["lost_units", "kwh_expected", "energy_excess_kwh", "scrap_material_cost", "process_waste_cost", "typ_perf"]:
            df[c] = pd.Series(dtype=float)
        return df, {}

    realization = float(A["savings_realization_factor"])
    ideal_uph = np.where(df["ideal_cycle_time_sec"] > 0, 3600.0 / df["ideal_cycle_time_sec"].where(df["ideal_cycle_time_sec"] > 0, 1), 0.0)
    cap = ideal_uph * df["run_minutes"] / 60.0
    perf = pd.Series(np.where(cap > 0, df["units"] / np.where(cap > 0, cap, 1), np.nan), index=df.index)
    typ = perf[df["run_minutes"] >= 45].groupby(df["machine"]).median()
    overall = float(perf[df["run_minutes"] >= 45].median()) if (df["run_minutes"] >= 45).any() else 0.85
    df["typ_perf"] = df["machine"].map(typ).fillna(overall if overall == overall else 0.85).clip(0.3, 1.0)

    g = df.groupby(["machine", "day"])

    # ---- downtime: contribution margin on good units not produced during UNPLANNED stops
    rate_per_min = ideal_uph / 60.0 * df["typ_perf"]
    df["lost_units"] = df["unplanned_dt"] * rate_per_min
    lost_good = df["lost_units"] * (1 - df["target_def_pct"] / 100.0)
    df["downtime_observed"] = lost_good * float(A["downtime_sellable_share"]) * df["cm_unit"].clip(lower=0)
    sched = (df["planned_minutes"] - df["planned_dt"]).clip(lower=0)
    allowed_dt = float(A["target_unplanned_downtime_pct"]) / 100.0 * sched.groupby([df["machine"], df["day"]]).transform("sum")
    dt_day = g["unplanned_dt"].transform("sum")
    f_dt = _ratio((dt_day - allowed_dt).clip(lower=0), dt_day)
    df["downtime_avoidable"] = df["downtime_observed"] * f_dt

    # ---- quality: conversion cost of scrapped units + rework cost
    df["quality_observed"] = df["scrapped"] * df["conv_cost"] + df["reworked"] * df["rework_cost"]
    allowed_def = (df["units"] * df["target_def_pct"] / 100.0).groupby([df["machine"], df["day"]]).transform("sum")
    def_day = g["defective"].transform("sum")
    f_q = _ratio((def_day - allowed_def).clip(lower=0), def_day)
    df["quality_avoidable"] = df["quality_observed"] * f_q

    # ---- material: scrapped material + process waste above BOM x units
    df["scrap_material_cost"] = df["scrapped"] * df["bom"] * df["mat_cost_kg"]
    proc_kg = (df["material_kg"] - df["units"] * df["bom"]).clip(lower=0)
    df["process_waste_cost"] = proc_kg * df["mat_cost_kg"]
    df["material_observed"] = df["scrap_material_cost"] + df["process_waste_cost"]
    allowed_proc = (float(A["target_process_waste_pct"]) / 100.0 * df["units"] * df["bom"]).groupby([df["machine"], df["day"]]).transform("sum")
    proc_day = proc_kg.groupby([df["machine"], df["day"]]).transform("sum")
    f_p = _ratio((proc_day - allowed_proc).clip(lower=0), proc_day)
    df["material_avoidable"] = df["scrap_material_cost"] * f_q + df["process_waste_cost"] * f_p

    # ---- energy: kWh above a baseline fitted on the machine's first 28 days (kWh = a + b x run minutes)
    baseline: dict[str, dict[str, float]] = {}
    expected = pd.Series(0.0, index=df.index)
    for mach, sub in df.groupby("machine"):
        first_day = sub["day"].min()
        ref = sub[sub["day"] < first_day + pd.Timedelta(days=ENERGY_BASELINE_DAYS)]
        x, y = ref["run_minutes"].to_numpy(float), ref["kwh"].to_numpy(float)
        if len(ref) >= 24 and np.ptp(x) > 0:
            b, a = np.polyfit(x, y, 1)
            baseline[mach] = {"a": float(a), "b": float(b), "ref_rows": int(len(ref)), "fallback": 0.0}
        else:
            per_min = float(y.sum() / max(x.sum(), 1.0)) if len(ref) else 0.0
            baseline[mach] = {"a": 0.0, "b": per_min, "ref_rows": int(len(ref)), "fallback": 1.0}
        bb = baseline[mach]
        expected.loc[sub.index] = np.clip(bb["a"] + bb["b"] * sub["run_minutes"], 0, None)
    df["kwh_expected"] = expected
    df["energy_excess_kwh"] = (df["kwh"] - df["kwh_expected"]).clip(lower=0)
    df["energy_observed"] = df["energy_excess_kwh"] * df["tariff"]
    tol = float(A["energy_tolerance_pct"]) / 100.0
    day_kwh = g["kwh"].transform("sum")
    day_exp = g["kwh_expected"].transform("sum")
    day_cost = g["energy_cost"].transform("sum")
    avg_tariff = np.where(day_kwh > 0, day_cost / day_kwh.where(day_kwh > 0, 1), 0.0)
    avoid_day = (day_kwh - day_exp * (1 + tol)).clip(lower=0) * avg_tariff
    obs_day = g["energy_observed"].transform("sum")
    df["energy_avoidable"] = df["energy_observed"] * _ratio(avoid_day, obs_day)

    for c in ROW_CATEGORIES:
        df[f"{c}_potential"] = df[f"{c}_avoidable"] * realization
    return df, baseline


def compute_inventory_loss(inv: pd.DataFrame, A: dict[str, Any]) -> pd.DataFrame:
    df = inv.copy()
    if df.empty:
        for c in ["value", "inventory_observed", "inventory_avoidable", "inventory_potential", "excess_qty", "avg_usage_28", "days_cover", "below_rop", "stockout", "slow_moving"]:
            df[c] = pd.Series(dtype=float)
        return df
    rate = float(A["inventory_carrying_rate_pct"]) / 100.0 / 365.0
    df["value"] = df["qty_on_hand"] * df["unit_cost"]
    df["inventory_observed"] = df["value"] * rate
    df["excess_qty"] = (df["qty_on_hand"] - df["max_level"]).clip(lower=0)
    df["inventory_avoidable"] = df["excess_qty"] * df["unit_cost"] * rate
    df["inventory_potential"] = df["inventory_avoidable"] * float(A["savings_realization_factor"])
    df["avg_usage_28"] = df.groupby("item_code")["daily_usage"].transform(lambda s: s.rolling(28, min_periods=7).mean())
    df["days_cover"] = np.where(df["avg_usage_28"] > 0, df["qty_on_hand"] / df["avg_usage_28"].where(df["avg_usage_28"] > 0, 1), np.nan)
    df["below_rop"] = df["qty_on_hand"] <= df["reorder_point"]
    df["stockout"] = df["qty_on_hand"] <= 0
    df["slow_moving"] = df["days_cover"] > float(A["slow_moving_days_of_cover"])
    return df


# ----------------------------------------------------------------------------- inventory filtering

def inventory_in_scope(inv: pd.DataFrame, f) -> tuple[pd.DataFrame, bool, str | None]:
    """Inventory is plant-level: it cannot be attributed to a line, machine or shift."""
    from app.analytics.frames import apply_filters

    sub = apply_filters(inv, f)
    if f.lines or f.machines or f.shifts:
        return sub.iloc[0:0], False, "Inventory carrying cost is plant-level and is excluded while line, machine or shift filters are active."
    if f.products:
        return sub[sub["sku"].isin(f.products)], True, "Only finished-goods inventory of the selected products is included."
    return sub, True, None


# ----------------------------------------------------------------------------- aggregations

def _sum_cat(df: pd.DataFrame, cat: str, tier: str) -> float:
    col = f"{cat}_{tier}"
    return float(df[col].sum()) if col in df and len(df) else 0.0


def category_summary(fact_f: pd.DataFrame, inv_f: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for cat, label in CATEGORIES:
        src = inv_f if cat == "inventory" else fact_f
        obs, av, pot = _sum_cat(src, cat, "observed"), _sum_cat(src, cat, "avoidable"), _sum_cat(src, cat, "potential")
        out.append({"category": cat, "label": label, "observed": money(obs), "avoidable": money(av), "potential_savings": money(pot)})
    return out


def totals(cats: list[dict[str, Any]]) -> dict[str, float]:
    return {"observed": float(sum(q2(c["observed"]) for c in cats)), "avoidable": float(sum(q2(c["avoidable"]) for c in cats)),
            "potential_savings": float(sum(q2(c["potential_savings"]) for c in cats))}


DIMENSIONS = {"machine": "machine", "line": "line", "product": "sku", "category": "category", "shift": "shift"}


def loss_by(fact_f: pd.DataFrame, inv_f: pd.DataFrame, dimension: str) -> list[dict[str, Any]]:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension '{dimension}'")
    key = DIMENSIONS[dimension]
    if fact_f.empty:
        return []
    cols = {f"{c}_{t}": "sum" for c in ROW_CATEGORIES for t in ("observed", "avoidable", "potential")}
    agg = fact_f.groupby(key).agg(cols).reset_index()
    label_col = {"machine": "machine_name", "line": "line_name", "product": "product_name"}.get(dimension)
    if label_col:
        labels = fact_f[[key, label_col]].drop_duplicates(key).rename(columns={label_col: "label"})
    else:
        labels = pd.DataFrame({key: fact_f[key].unique()})
        labels["label"] = labels[key]
    agg = agg.merge(labels, on=key)
    if dimension in ("product", "category") and len(inv_f):
        ik = "sku" if dimension == "product" else "category"
        fg = inv_f[inv_f["item_type"] == "finished_good"].groupby(ik).agg(inventory_observed=("inventory_observed", "sum"), inventory_avoidable=("inventory_avoidable", "sum"),
                                                                           inventory_potential=("inventory_potential", "sum")).reset_index().rename(columns={ik: key})
        agg = agg.merge(fg, on=key, how="left")
    for t in ("observed", "avoidable", "potential"):
        agg[f"inventory_{t}"] = agg[f"inventory_{t}"].fillna(0.0) if f"inventory_{t}" in agg else 0.0
    agg["total_observed"] = agg[[f"{c}_observed" for c in ROW_CATEGORIES + ["inventory"]]].sum(axis=1)
    agg["total_avoidable"] = agg[[f"{c}_avoidable" for c in ROW_CATEGORIES + ["inventory"]]].sum(axis=1)
    agg["total_potential"] = agg[[f"{c}_potential" for c in ROW_CATEGORIES + ["inventory"]]].sum(axis=1)
    agg = agg.sort_values("total_observed", ascending=False)
    rows = []
    for _, r in agg.iterrows():
        row = {"key": r[key], "label": r["label"], "total_observed": money(r["total_observed"]), "total_avoidable": money(r["total_avoidable"]), "total_potential": money(r["total_potential"])}
        for c, _l in CATEGORIES:
            row[f"{c}_observed"] = money(r.get(f"{c}_observed", 0.0))
            row[f"{c}_avoidable"] = money(r.get(f"{c}_avoidable", 0.0))
        rows.append(row)
    return rows


GRAINS = {"day": "D", "week": "W-SUN", "month": "M"}


def _period(series: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return series.dt.normalize()
    if grain == "week":
        return series.dt.to_period("W-SUN").dt.start_time
    if grain == "month":
        return series.dt.to_period("M").dt.start_time
    raise ValueError(f"Unsupported grain '{grain}'")


def loss_trend(fact_f: pd.DataFrame, inv_f: pd.DataFrame, grain: str = "week") -> list[dict[str, Any]]:
    parts = []
    if len(fact_f):
        t = fact_f.assign(period=_period(fact_f["day"], grain)).groupby("period")[[f"{c}_{t}" for c in ROW_CATEGORIES for t in ("observed", "avoidable")]].sum()
        parts.append(t)
    if len(inv_f):
        ti = inv_f.assign(period=_period(inv_f["day"], grain)).groupby("period")[["inventory_observed", "inventory_avoidable"]].sum()
        parts.append(ti)
    if not parts:
        return []
    allp = pd.concat(parts, axis=1).fillna(0.0).sort_index()
    rows = []
    for ts, r in allp.iterrows():
        row = {"period": ts.date().isoformat()}
        tot_o = tot_a = 0.0
        for c, _l in CATEGORIES:
            o, a = float(r.get(f"{c}_observed", 0.0)), float(r.get(f"{c}_avoidable", 0.0))
            row[f"{c}_observed"], row[f"{c}_avoidable"] = money(o), money(a)
            tot_o += o
            tot_a += a
        row["total_observed"], row["total_avoidable"] = money(tot_o), money(tot_a)
        rows.append(row)
    return rows


DRILL_COLUMNS = {
    "downtime": ["period_start", "machine", "sku", "unplanned_dt", "lost_units", "cm_unit", "downtime_observed", "downtime_avoidable"],
    "quality": ["period_start", "machine", "sku", "units", "defective", "scrapped", "reworked", "quality_observed", "quality_avoidable"],
    "energy": ["period_start", "machine", "kwh", "kwh_expected", "energy_excess_kwh", "tariff", "energy_observed", "energy_avoidable"],
    "material": ["period_start", "machine", "sku", "units", "scrapped", "material_kg", "scrap_material_cost", "process_waste_cost", "material_observed", "material_avoidable"],
    "inventory": ["snapshot_date", "item_code", "item_name", "qty_on_hand", "max_level", "excess_qty", "unit_cost", "value", "inventory_observed", "inventory_avoidable"],
}


def drilldown(fact_f: pd.DataFrame, inv_f: pd.DataFrame, category: str, sort: str | None, desc: bool, page: int, size: int) -> dict[str, Any]:
    if category not in DRILL_COLUMNS:
        raise ValueError(f"Unsupported category '{category}'")
    src = inv_f if category == "inventory" else fact_f
    cols = DRILL_COLUMNS[category]
    obs_col = f"{category}_observed"
    sub = src[src[obs_col] > 0] if len(src) else src
    sort_col = sort if sort in cols else obs_col
    sub = sub.sort_values(sort_col, ascending=not desc)
    total = len(sub)
    page = max(1, page)
    size = max(1, min(size, 500))
    chunk = sub.iloc[(page - 1) * size : page * size]
    rows = []
    for _, r in chunk.iterrows():
        row = {}
        for c in cols:
            v = r.get(c)
            if isinstance(v, pd.Timestamp):
                v = v.isoformat(sep=" ")
            elif isinstance(v, (float, np.floating)):
                v = num(v, 3)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            row[c] = v
        rows.append(row)
    return {"category": category, "columns": cols, "rows": rows, "total": int(total), "page": page, "size": size,
            "totals": {"observed": money(_sum_cat(src, category, "observed")), "avoidable": money(_sum_cat(src, category, "avoidable"))}}
