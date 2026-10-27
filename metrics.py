"""Transparent, testable metric calculations on filtered DataFrames.

All functions are pure (DataFrame in, plain dict/list out), never raise on empty input and never
divide by zero (they return None for undefined ratios).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.analytics.money import num, pct, safe_div


def production_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"units_produced": 0, "good_units": 0, "defective_units": 0, "target_units": 0.0, "target_attainment_pct": None, "defect_rate_pct": None,
                "first_pass_yield_pct": None, "final_yield_pct": None, "planned_minutes": 0, "planned_downtime_minutes": 0, "unplanned_downtime_minutes": 0, "run_minutes": 0,
                "availability_pct": None, "performance_pct": None, "oee_pct": None, "labor_cost": 0.0, "labor_cost_per_good_unit": None, "material_kg": 0.0, "scrapped_units": 0, "reworked_units": 0}
    units, good, defective = int(df["units"].sum()), int(df["good"].sum()), int(df["defective"].sum())
    target = float(df["target_units"].sum())
    planned, pdt, udt, run = int(df["planned_minutes"].sum()), int(df["planned_dt"].sum()), int(df["unplanned_dt"].sum()), int(df["run_minutes"].sum())
    reworked, scrapped = int(df["reworked"].sum()), int(df["scrapped"].sum())
    ideal_uph = np.where(df["ideal_cycle_time_sec"] > 0, 3600.0 / df["ideal_cycle_time_sec"].where(df["ideal_cycle_time_sec"] > 0, 1), 0.0)
    ideal_capacity = float((ideal_uph * df["run_minutes"] / 60.0).sum())
    availability = pct(run, planned - pdt)
    performance = pct(units, ideal_capacity)
    quality = pct(good, units)
    oee = None if None in (availability, performance, quality) else availability * performance * quality / 10000.0
    labor = float(df["labor_cost"].sum())
    return {
        "units_produced": units, "good_units": good, "defective_units": defective, "target_units": num(target, 1),
        "target_attainment_pct": num(pct(units, target), 2), "defect_rate_pct": num(pct(defective, units), 3),
        "first_pass_yield_pct": num(pct(good, units), 3), "final_yield_pct": num(pct(good + reworked, units), 3),
        "planned_minutes": planned, "planned_downtime_minutes": pdt, "unplanned_downtime_minutes": udt, "run_minutes": run,
        "availability_pct": num(availability, 2), "performance_pct": num(performance, 2), "oee_pct": num(oee, 2),
        "labor_cost": num(labor, 2), "labor_cost_per_good_unit": num(safe_div(labor, good), 3), "material_kg": num(float(df["material_kg"].sum()), 1),
        "scrapped_units": scrapped, "reworked_units": reworked,
    }


def output_by(df: pd.DataFrame, key: str, label_col: str | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    g = df.groupby(key).agg(units=("units", "sum"), good=("good", "sum"), defective=("defective", "sum"), target=("target_units", "sum"), unplanned_dt=("unplanned_dt", "sum"),
                            planned=("planned_minutes", "sum"), run=("run_minutes", "sum"), labor=("labor_cost", "sum")).reset_index()
    if label_col:
        lab = df[[key, label_col]].drop_duplicates(key).rename(columns={label_col: "label"})
        g = g.merge(lab, on=key)
    else:
        g["label"] = g[key]
    rows = []
    for _, r in g.sort_values("units", ascending=False).iterrows():
        rows.append({"key": r[key], "label": r["label"], "units": int(r["units"]), "good": int(r["good"]), "defective": int(r["defective"]), "target": num(r["target"], 1),
                     "attainment_pct": num(pct(r["units"], r["target"]), 2), "defect_rate_pct": num(pct(r["defective"], r["units"]), 3),
                     "unplanned_downtime_pct": num(pct(r["unplanned_dt"], r["planned"]), 2), "labor_cost_per_good_unit": num(safe_div(r["labor"], r["good"]), 3)})
    return rows


def _period(series: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return series.dt.normalize()
    if grain == "week":
        return series.dt.to_period("W-SUN").dt.start_time
    if grain == "month":
        return series.dt.to_period("M").dt.start_time
    raise ValueError(f"Unsupported grain '{grain}'")


def production_trend(df: pd.DataFrame, grain: str = "day") -> list[dict[str, Any]]:
    if df.empty:
        return []
    t = df.assign(period=_period(df["day"], grain)).groupby("period").agg(
        units=("units", "sum"), good=("good", "sum"), defective=("defective", "sum"), target=("target_units", "sum"), planned=("planned_minutes", "sum"),
        planned_dt=("planned_dt", "sum"), unplanned_dt=("unplanned_dt", "sum"), run=("run_minutes", "sum"), kwh=("kwh", "sum"), energy_cost=("energy_cost", "sum"),
        scrapped=("scrapped", "sum")).reset_index()
    rows = []
    for _, r in t.iterrows():
        rows.append({"period": r["period"].date().isoformat(), "units": int(r["units"]), "good": int(r["good"]), "defective": int(r["defective"]), "target": num(r["target"], 1),
                     "attainment_pct": num(pct(r["units"], r["target"]), 2), "defect_rate_pct": num(pct(r["defective"], r["units"]), 3),
                     "unplanned_downtime_min": int(r["unplanned_dt"]), "planned_downtime_min": int(r["planned_dt"]),
                     "unplanned_downtime_pct": num(pct(r["unplanned_dt"], r["planned"]), 2), "kwh": num(r["kwh"], 1), "energy_cost": num(r["energy_cost"], 2),
                     "kwh_per_good_unit": num(safe_div(r["kwh"], r["good"]), 4)})
    return rows


def quality_summary(df: pd.DataFrame, qdf: pd.DataFrame) -> dict[str, Any]:
    base = production_summary(df)
    cats: list[dict[str, Any]] = []
    if len(qdf):
        g = qdf.groupby("defect_category").agg(defects=("defect_units", "sum"), scrapped=("scrapped_units", "sum"), reworked=("reworked_units", "sum")).reset_index().sort_values("defects", ascending=False)
        total = float(g["defects"].sum())
        for _, r in g.iterrows():
            cats.append({"category": r["defect_category"], "defect_units": int(r["defects"]), "scrapped_units": int(r["scrapped"]), "reworked_units": int(r["reworked"]), "share_pct": num(pct(r["defects"], total), 1)})
    return {**base, "categories": cats}


def defect_trend_by_category(qdf: pd.DataFrame, grain: str = "week") -> list[dict[str, Any]]:
    if qdf.empty:
        return []
    t = qdf.assign(period=_period(qdf["day"], grain)).pivot_table(index="period", columns="defect_category", values="defect_units", aggfunc="sum", fill_value=0).sort_index()
    rows = []
    for ts, r in t.iterrows():
        row: dict[str, Any] = {"period": ts.date().isoformat()}
        row.update({c: int(v) for c, v in r.items()})
        rows.append(row)
    return rows


# --------------------------------------------------------------------------------- downtime

def downtime_summary(df: pd.DataFrame, ev: pd.DataFrame) -> dict[str, Any]:
    """Unplanned vs planned downtime, MTBF and MTTR.

    * minutes come from the hourly production records (measured), events provide counts and reasons.
    * MTBF  = machine run hours / number of unplanned stops (None when there are no stops)
    * MTTR  = mean duration of unplanned stops (None when there are no stops)
    """
    unpl_ev = ev[~ev["planned"]] if len(ev) else ev
    plan_ev = ev[ev["planned"]] if len(ev) else ev
    n_unpl = int(len(unpl_ev))
    run_hours = float(df["run_minutes"].sum()) / 60.0 if len(df) else 0.0
    total_unpl_min = int(df["unplanned_dt"].sum()) if len(df) else 0
    planned_min = int(df["planned_minutes"].sum()) if len(df) else 0
    return {
        "unplanned_minutes": total_unpl_min, "planned_minutes": int(df["planned_dt"].sum()) if len(df) else 0,
        "unplanned_pct_of_planned_time": num(pct(total_unpl_min, planned_min), 2),
        "unplanned_events": n_unpl, "planned_events": int(len(plan_ev)),
        "mtbf_hours": num(safe_div(run_hours, n_unpl), 2), "mttr_minutes": num(float(unpl_ev["duration_minutes"].mean()) if n_unpl else None, 1),
        "run_hours": num(run_hours, 1),
    }


def downtime_by_machine(df: pd.DataFrame, ev: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    base = df.groupby("machine").agg(line=("line", "first"), planned=("planned_minutes", "sum"), unplanned=("unplanned_dt", "sum"), planned_dt=("planned_dt", "sum"), run=("run_minutes", "sum"),
                                     lost_cost=("downtime_observed", "sum")).reset_index()
    if len(ev):
        u = ev[~ev["planned"]].groupby("machine").agg(events=("event_id", "count"), mttr=("duration_minutes", "mean")).reset_index()
        base = base.merge(u, on="machine", how="left")
    else:
        base["events"], base["mttr"] = 0, np.nan
    base["events"] = base["events"].fillna(0).astype(int)
    rows = []
    for _, r in base.sort_values("unplanned", ascending=False).iterrows():
        rows.append({"machine": r["machine"], "line": r["line"], "unplanned_minutes": int(r["unplanned"]), "planned_minutes": int(r["planned_dt"]),
                     "unplanned_pct": num(pct(r["unplanned"], r["planned"]), 2), "events": int(r["events"]),
                     "mtbf_hours": num(safe_div(r["run"] / 60.0, r["events"]), 1), "mttr_minutes": num(r["mttr"], 1), "estimated_cm_impact": num(r["lost_cost"], 2)})
    return rows


def downtime_by_reason(ev: pd.DataFrame, planned: bool | None = False) -> list[dict[str, Any]]:
    if ev.empty:
        return []
    sub = ev if planned is None else ev[ev["planned"] == planned]
    if sub.empty:
        return []
    g = sub.groupby(["reason_code", "reason_category", "planned"]).agg(events=("event_id", "count"), minutes=("duration_minutes", "sum"), mean=("duration_minutes", "mean")).reset_index().sort_values("minutes", ascending=False)
    total = float(g["minutes"].sum())
    cum = 0.0
    rows = []
    for _, r in g.iterrows():
        cum += r["minutes"]
        rows.append({"reason_code": r["reason_code"], "category": r["reason_category"], "planned": bool(r["planned"]), "events": int(r["events"]), "minutes": num(r["minutes"], 1),
                     "mean_minutes": num(r["mean"], 1), "share_pct": num(pct(r["minutes"], total), 1), "cumulative_pct": num(pct(cum, total), 1)})
    return rows


def downtime_machine_reason_matrix(ev: pd.DataFrame) -> dict[str, Any]:
    sub = ev[~ev["planned"]] if len(ev) else ev
    if sub.empty:
        return {"machines": [], "reasons": [], "minutes": []}
    pv = sub.pivot_table(index="machine", columns="reason_code", values="duration_minutes", aggfunc="sum", fill_value=0)
    pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index]
    return {"machines": list(pv.index), "reasons": list(pv.columns), "minutes": [[num(v, 1) for v in row] for row in pv.to_numpy()]}


# --------------------------------------------------------------------------------- energy

def energy_summary(df: pd.DataFrame, A: dict[str, Any]) -> dict[str, Any]:
    if df.empty:
        return {"kwh": 0.0, "energy_cost": 0.0, "avg_tariff": None, "kwh_per_good_unit": None, "cost_per_good_unit": None, "excess_kwh": 0.0, "excess_cost": 0.0, "abnormal_machine_days": 0}
    kwh, cost, good = float(df["kwh"].sum()), float(df["energy_cost"].sum()), float(df["good"].sum())
    return {"kwh": num(kwh, 1), "energy_cost": num(cost, 2), "avg_tariff": num(safe_div(cost, kwh), 3), "kwh_per_good_unit": num(safe_div(kwh, good), 4),
            "cost_per_good_unit": num(safe_div(cost, good), 4), "excess_kwh": num(float(df["energy_excess_kwh"].sum()), 1), "excess_cost": num(float(df["energy_observed"].sum()), 2),
            "abnormal_machine_days": int(len(abnormal_energy_days(df, A)))}


def energy_by(df: pd.DataFrame, key: str, label_col: str | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    g = df.groupby(key).agg(kwh=("kwh", "sum"), cost=("energy_cost", "sum"), good=("good", "sum"), run=("run_minutes", "sum"), excess=("energy_excess_kwh", "sum"), excess_cost=("energy_observed", "sum")).reset_index()
    if label_col:
        g = g.merge(df[[key, label_col]].drop_duplicates(key).rename(columns={label_col: "label"}), on=key)
    else:
        g["label"] = g[key]
    rows = []
    for _, r in g.sort_values("cost", ascending=False).iterrows():
        rows.append({"key": r[key], "label": r["label"], "kwh": num(r["kwh"], 1), "cost": num(r["cost"], 2), "kwh_per_good_unit": num(safe_div(r["kwh"], r["good"]), 4),
                     "kwh_per_run_hour": num(safe_div(r["kwh"], r["run"] / 60.0), 2), "excess_kwh": num(r["excess"], 1), "excess_cost": num(r["excess_cost"], 2)})
    return rows


def abnormal_energy_days(df: pd.DataFrame, A: dict[str, Any]) -> pd.DataFrame:
    """Machine-days whose kWh exceeds the fitted baseline by more than the tolerance."""
    if df.empty:
        return pd.DataFrame(columns=["machine", "day", "kwh", "kwh_expected", "excess_pct", "excess_kwh", "excess_cost"])
    d = df.groupby(["machine", "day"]).agg(kwh=("kwh", "sum"), kwh_expected=("kwh_expected", "sum"), excess_cost=("energy_observed", "sum")).reset_index()
    d = d[d["kwh_expected"] > 0]
    d["excess_pct"] = (d["kwh"] / d["kwh_expected"] - 1.0) * 100.0
    d["excess_kwh"] = (d["kwh"] - d["kwh_expected"]).clip(lower=0)
    return d[d["excess_pct"] > float(A["energy_tolerance_pct"])].sort_values("excess_pct", ascending=False)


# --------------------------------------------------------------------------------- inventory

def inventory_status(inv: pd.DataFrame, as_of: pd.Timestamp | None, A: dict[str, Any]) -> list[dict[str, Any]]:
    """Latest snapshot per item on or before `as_of`."""
    if inv.empty:
        return []
    sub = inv if as_of is None else inv[inv["day"] <= as_of]
    if sub.empty:
        return []
    latest = sub.sort_values("snapshot_date").groupby("item_code").tail(1)
    rows = []
    for _, r in latest.sort_values(["item_type", "item_code"]).iterrows():
        status = "stockout" if r["qty_on_hand"] <= 0 else ("below_reorder_point" if r["below_rop"] else ("excess" if r["excess_qty"] > 0 else "ok"))
        rows.append({"item_code": r["item_code"], "item_name": r["item_name"], "item_type": r["item_type"], "unit": r["unit"], "as_of": r["snapshot_date"].date().isoformat(),
                     "qty_on_hand": num(r["qty_on_hand"], 1), "value": num(r["value"], 2), "reorder_point": num(r["reorder_point"], 1), "max_level": num(r["max_level"], 1),
                     "days_of_cover": num(r["days_cover"], 1), "slow_moving": bool(r["slow_moving"]) if r["slow_moving"] == r["slow_moving"] else False, "status": status,
                     "excess_qty": num(r["excess_qty"], 1), "carrying_cost_per_day": num(r["inventory_observed"], 2)})
    return rows


def stockout_events(inv: pd.DataFrame) -> list[dict[str, Any]]:
    """Consecutive zero-stock days of one item form one stockout event."""
    if inv.empty:
        return []
    out = []
    for code, g in inv.sort_values("snapshot_date").groupby("item_code"):
        flag = g["stockout"].to_numpy()
        dates = g["snapshot_date"].to_numpy()
        i = 0
        while i < len(flag):
            if flag[i]:
                j = i
                while j + 1 < len(flag) and flag[j + 1]:
                    j += 1
                out.append({"item_code": code, "item_name": g["item_name"].iloc[0], "start": pd.Timestamp(dates[i]).date().isoformat(), "end": pd.Timestamp(dates[j]).date().isoformat(), "days": int(j - i + 1)})
                i = j + 1
            else:
                i += 1
    return sorted(out, key=lambda e: e["start"])


def inventory_trend(inv: pd.DataFrame) -> list[dict[str, Any]]:
    if inv.empty:
        return []
    t = inv.groupby(["day", "item_type"])["value"].sum().unstack(fill_value=0).reset_index().sort_values("day")
    return [{"date": r["day"].date().isoformat(), "raw_material_value": num(r.get("raw_material", 0), 2), "finished_goods_value": num(r.get("finished_good", 0), 2)} for _, r in t.iterrows()]
