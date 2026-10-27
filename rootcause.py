"""Root Cause Explorer: observational analytics only. Everything here is association, never proven causation."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..config import get_settings
from .analytics import Filters, aggregate, event_frame, load_frame, records, sdiv

CAUSATION_NOTE = "Correlation does not prove causation. These are observed associations in the selected data; confirm with a controlled investigation before acting."
MIN_N = 30


def _machine_day(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["machine_id", "machine_code", "date"]).agg(
        units=("units", "sum"), defective=("defective", "sum"), unpl=("unpl_down", "sum"), planned=("planned_down", "sum"),
        period=("period_minutes", "sum"), kwh=("kwh", "sum"), target=("target", "sum"), ideal=("ideal_units", "sum"),
        excess_kwh=("excess_kwh", "sum"), base_exp=("base_kwh_unit", "mean")).reset_index()
    g["defect_rate_pct"] = sdiv(g.defective, g.units) * 100
    g["unplanned_downtime_pct"] = sdiv(g.unpl, g.period) * 100
    g["planned_downtime_pct"] = sdiv(g.planned, g.period) * 100
    g["kwh_per_unit"] = sdiv(g.kwh, g.units)
    g["efficiency_pct"] = sdiv(g.units, g.ideal) * 100
    g["attainment_pct"] = sdiv(g.units, g.target) * 100
    return g


CORR_VARS = ["unplanned_downtime_pct", "planned_downtime_pct", "defect_rate_pct", "kwh_per_unit", "efficiency_pct", "attainment_pct"]


def correlations(md: pd.DataFrame) -> dict:
    d = md[CORR_VARS].replace([np.inf, -np.inf], np.nan)
    if len(d.dropna(how="all")) < MIN_N:
        return dict(available=False, reason=f"Need at least {MIN_N} machine-days for correlation analysis (have {len(d)}). Widen the date range.")
    pairs = []
    for i, a in enumerate(CORR_VARS):
        for b in CORR_VARS[i + 1:]:
            x = d[[a, b]].dropna()
            n = len(x)
            if n < MIN_N or x[a].std() == 0 or x[b].std() == 0:
                continue
            # machine-level differences dominate raw correlations; also report within-machine (demeaned) association
            r = float(np.corrcoef(x[a], x[b])[0, 1])
            sub = md.loc[x.index, ["machine_id"]].join(x)
            dm = sub[[a, b]] - sub.groupby("machine_id")[[a, b]].transform("mean")
            rw = float(np.corrcoef(dm[a], dm[b])[0, 1]) if dm[a].std() > 0 and dm[b].std() > 0 else None
            noise = 2 / math.sqrt(n)
            strength = "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak"
            pairs.append(dict(a=a, b=b, r=round(r, 3), r_within_machine=None if rw is None else round(rw, 3), n=n,
                              exceeds_noise=bool(abs(r) > noise), strength=strength))
    pairs.sort(key=lambda p: abs(p["r"]), reverse=True)
    matrix = d.corr().round(3).replace({np.nan: None}).to_dict()
    return dict(available=True, variables=CORR_VARS, matrix=matrix, pairs=pairs, unit="machine-day", note=CAUSATION_NOTE)


def group_comparison(df: pd.DataFrame, cfg) -> dict:
    out = {}
    overall = aggregate(df, None, cfg).iloc[0]
    for name, key in [("machine", ["machine_code"]), ("shift", ["shift"]), ("line", ["line_name"]), ("product", ["product_sku"])]:
        a = aggregate(df, key, cfg)
        a["defect_index"] = a.defect_rate_pct / overall.defect_rate_pct if overall.defect_rate_pct else np.nan
        a["downtime_index"] = a.unplanned_downtime_pct / overall.unplanned_downtime_pct if overall.unplanned_downtime_pct else np.nan
        a["energy_index"] = a.kwh_per_good_unit / overall.kwh_per_good_unit if overall.kwh_per_good_unit else np.nan
        cols = key + ["units", "defect_rate_pct", "unplanned_downtime_pct", "kwh_per_good_unit", "efficiency_pct", "defect_index", "downtime_index", "energy_index"]
        out[name] = records(a[cols], 3)
    out["note"] = "Index = group value / overall value (1.00 = average). Differences between groups may reflect product mix or machine age, not just the grouping variable."
    return out


def trend_comparison(df: pd.DataFrame, cfg) -> dict:
    if df.empty or df.date.nunique() < 14:
        return dict(available=False, reason="Need at least 14 distinct days to compare the first and second half of the window.")
    mid = df.date.min() + (df.date.max() - df.date.min()) / 2
    first, second = df[df.date <= mid], df[df.date > mid]
    a1, a2 = aggregate(first, ["machine_code"], cfg).set_index("machine_code"), aggregate(second, ["machine_code"], cfg).set_index("machine_code")
    rows = []
    for code in a2.index:
        if code not in a1.index:
            continue
        rows.append(dict(
            machine_code=code,
            unplanned_downtime_pct_first=a1.loc[code, "unplanned_downtime_pct"], unplanned_downtime_pct_second=a2.loc[code, "unplanned_downtime_pct"],
            defect_rate_pct_first=a1.loc[code, "defect_rate_pct"], defect_rate_pct_second=a2.loc[code, "defect_rate_pct"],
            kwh_per_good_unit_first=a1.loc[code, "kwh_per_good_unit"], kwh_per_good_unit_second=a2.loc[code, "kwh_per_good_unit"],
        ))
    t = pd.DataFrame(rows)
    for k in ("unplanned_downtime_pct", "defect_rate_pct", "kwh_per_good_unit"):
        t[f"{k}_change"] = t[f"{k}_second"] - t[f"{k}_first"]
    t = t.sort_values("unplanned_downtime_pct_change", ascending=False)
    return dict(available=True, split_date=mid.date().isoformat(), machines=records(t, 3),
                note="Compares the first and second half of the selected window. A change is a pattern in time, not an explanation.")


def downtime_reason_matrix(db: Session, f: Filters) -> dict:
    ev = event_frame(db, f)
    ev = ev[~ev.planned.astype(bool)] if len(ev) else ev
    if ev.empty:
        return dict(available=False, reason="No unplanned downtime events in the selected window.")
    pv = ev.pivot_table(index="machine_code", columns="reason_code", values="duration_min", aggfunc="sum", fill_value=0).round(1)
    top = ev.groupby(["machine_code", "reason_code"]).duration_min.sum().sort_values(ascending=False).head(10).reset_index()
    return dict(available=True, reasons=list(pv.columns), machines=list(pv.index), minutes=pv.values.tolist(), top_combinations=records(top, 1),
                note="Event views ignore the product filter (events are not product-specific).")


def outliers(md: pd.DataFrame, z_thresh: float = 3.5) -> dict:
    res = []
    for metric in ("defect_rate_pct", "kwh_per_unit", "unplanned_downtime_pct"):
        for code, g in md.groupby("machine_code"):
            s = g[metric].replace([np.inf, -np.inf], np.nan).dropna()
            if len(s) < 20:
                continue
            med = s.median()
            mad = (s - med).abs().median()
            if mad == 0:
                continue
            z = 0.6745 * (s - med) / mad
            for idx in z[z.abs() > z_thresh].index:
                res.append(dict(machine_code=code, date=g.loc[idx, "date"].date().isoformat(), metric=metric, value=float(s[idx]), expected=float(med), robust_z=float(z[idx])))
    res.sort(key=lambda r: abs(r["robust_z"]), reverse=True)
    if md.empty or md.groupby("machine_code").size().max() < 20:
        return dict(available=False, reason="Need at least 20 days per machine for outlier detection.")
    return dict(available=True, method="Modified z-score (median/MAD) within each machine, |z| > 3.5", count=len(res), items=records(pd.DataFrame(res[:50]), 3) if res else [],
                drilldown="Use the machine and date to list the underlying records via /api/production.")


def explore(db: Session, f: Filters, cfg=None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    if df.empty:
        msg = "No production records in the selected window."
        return dict(note=CAUSATION_NOTE, correlations=dict(available=False, reason=msg), groups=None, trends=dict(available=False, reason=msg),
                    reasons=dict(available=False, reason=msg), outliers=dict(available=False, reason=msg))
    md = _machine_day(df)
    return dict(note=CAUSATION_NOTE, correlations=correlations(md), groups=group_comparison(df, cfg), trends=trend_comparison(df, cfg),
                reasons=downtime_reason_matrix(db, f), outliers=outliers(md))
