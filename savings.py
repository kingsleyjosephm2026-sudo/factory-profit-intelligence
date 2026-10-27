"""Savings verification. Evidence status is computed by the server from the data; users cannot type 'verified'.

Statuses:
  identified - an opportunity exists but there is no intervention/baseline yet
  forecast   - an expected saving is recorded but no post-intervention data exists
  estimated  - post-intervention data exists but one or more evidence checks failed
  verified   - every evidence check passed (baseline and post periods long enough, comparable volume,
               statistically distinguishable change, documented assumptions). This still is not a controlled
               experiment, so the result is labelled "verified against baseline", not "proven causal".
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .. import models as m
from ..config import Settings, get_settings
from .analytics import Filters, data_bounds, load_frame
from .finance import money, savings_from_rates

MIN_BASELINE_DAYS, MIN_POST_DAYS, MIN_COVERAGE, VOLUME_BAND, MIN_T, MIN_REL_IMPROVEMENT = 28, 14, 0.80, 0.30, 2.0, 0.05

CATEGORY = {
    "downtime": dict(driver="period_minutes", driver_label="scheduled minutes", loss="loss_downtime",
                     natural="Unplanned downtime %", formula="(baseline cost per scheduled minute - post cost per scheduled minute) x post scheduled minutes"),
    "quality": dict(driver="units", driver_label="units produced", loss="loss_quality",
                    natural="Defect rate %", formula="(baseline quality cost per unit - post quality cost per unit) x post units produced"),
    "energy": dict(driver="units", driver_label="units produced", loss="loss_energy",
                   natural="kWh per unit", formula="(baseline excess-energy cost per unit - post excess-energy cost per unit) x post units produced"),
    "material": dict(driver="units", driver_label="units produced", loss="loss_material",
                     natural="Material waste cost per unit", formula="(baseline material-waste cost per unit - post material-waste cost per unit) x post units produced"),
}


def _scope_filters(init: m.SavingsInitiative, start: date, end: date) -> Filters:
    kw = {}
    if init.scope_type == "line":
        kw["line_id"] = init.scope_id
    elif init.scope_type == "machine":
        kw["machine_id"] = init.scope_id
    return Filters(start, end, **kw)


def period_stats(db: Session, init: m.SavingsInitiative, start: date, end: date, cfg: Settings) -> dict:
    spec = CATEGORY[init.category]
    df = load_frame(db, _scope_filters(init, start, end), cfg)
    n_days_total = (end - start).days + 1
    if df.empty:
        return dict(days_with_data=0, days_total=n_days_total, coverage=0.0, rate=None, driver_total=0.0, daily_rates=[], daily_driver=0.0, natural=None)
    daily = df.groupby("date").agg(loss=(spec["loss"], "sum"), driver=(spec["driver"], "sum"), units=("units", "sum"), defective=("defective", "sum"),
                                   unpl=("unpl_down", "sum"), period=("period_minutes", "sum"), kwh=("kwh", "sum"), mat=("material_cost", "sum"))
    daily = daily[daily.driver > 0]
    rates = (daily.loss / daily.driver).to_numpy()
    tot_driver = float(daily.driver.sum())
    natural = {"downtime": daily.unpl.sum() / daily.period.sum() * 100, "quality": daily.defective.sum() / daily.units.sum() * 100 if daily.units.sum() else None,
               "energy": daily.kwh.sum() / daily.units.sum() if daily.units.sum() else None, "material": daily.loss.sum() / daily.units.sum() if daily.units.sum() else None}[init.category]
    return dict(days_with_data=int(len(daily)), days_total=n_days_total, coverage=len(daily) / n_days_total if n_days_total else 0.0,
                rate=float(daily.loss.sum() / tot_driver) if tot_driver else None, driver_total=tot_driver, daily_rates=rates.tolist(),
                daily_driver=tot_driver / len(daily) if len(daily) else 0.0, natural=None if natural is None else float(natural))


def welch_t(a: list[float], b: list[float]) -> float | None:
    if len(a) < 7 or len(b) < 7:
        return None
    va, vb = np.var(a, ddof=1) / len(a), np.var(b, ddof=1) / len(b)
    if va + vb == 0:
        return None
    return float((np.mean(a) - np.mean(b)) / math.sqrt(va + vb))


def evaluate(db: Session, init: m.SavingsInitiative, cfg: Settings | None = None) -> dict:
    cfg = cfg or get_settings()
    spec = CATEGORY[init.category]
    lo, hi = data_bounds(db)
    checks: list[dict] = []
    result: dict = dict(category=init.category, formula=spec["formula"], driver=spec["driver_label"], natural_metric=spec["natural"], value_source=init.value_source)

    def chk(name, passed, detail):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    have_periods = all([init.baseline_start, init.baseline_end, init.post_start, init.post_end, init.intervention_date])
    post_has_data = bool(have_periods and hi is not None and init.post_start <= hi and init.intervention_date <= hi)
    savings = None
    status = "identified"

    if init.value_source == "manual":
        if init.baseline_value is not None and init.post_value is not None and init.manual_volume is not None:
            savings = savings_from_rates(init.baseline_value, init.post_value, init.manual_volume)
        chk("Values computed from loaded data", False, "Baseline and post values were entered manually and cannot be checked against the dataset, so the result can be at most an estimate.")
        status = "estimated" if savings is not None and have_periods else ("forecast" if (init.expected_savings or 0) > 0 else "identified")
        result.update(baseline_rate=init.baseline_value, post_rate=init.post_value, post_volume=init.manual_volume)
    elif have_periods:
        b = period_stats(db, init, init.baseline_start, init.baseline_end, cfg)
        p = period_stats(db, init, init.post_start, init.post_end, cfg) if post_has_data else None
        result["baseline"] = {k: v for k, v in b.items() if k != "daily_rates"}
        if p:
            result["post"] = {k: v for k, v in p.items() if k != "daily_rates"}
        if b["rate"] is not None:
            init.baseline_value = b["natural"]
        if p and p["rate"] is not None:
            init.post_value = p["natural"]
            savings = savings_from_rates(b["rate"], p["rate"], p["driver_total"])
            result.update(baseline_rate=b["rate"], post_rate=p["rate"], post_volume=p["driver_total"])
        chk("Baseline long enough", (init.baseline_end - init.baseline_start).days + 1 >= MIN_BASELINE_DAYS, f"Baseline spans {(init.baseline_end - init.baseline_start).days + 1} days; at least {MIN_BASELINE_DAYS} required.")
        chk("Baseline data coverage", b["coverage"] >= MIN_COVERAGE, f"{b['days_with_data']} of {b['days_total']} baseline days have data ({b['coverage']:.0%}); at least {MIN_COVERAGE:.0%} required.")
        chk("Periods ordered", init.baseline_end < init.intervention_date <= init.post_start <= init.post_end, "Baseline must end before the intervention date, and the post period must start on or after it.")
        if p:
            chk("Post period long enough", (init.post_end - init.post_start).days + 1 >= MIN_POST_DAYS, f"Post period spans {(init.post_end - init.post_start).days + 1} days; at least {MIN_POST_DAYS} required.")
            chk("Post data coverage", p["coverage"] >= MIN_COVERAGE, f"{p['days_with_data']} of {p['days_total']} post days have data ({p['coverage']:.0%}).")
            vol_ok = b["daily_driver"] > 0 and abs(p["daily_driver"] / b["daily_driver"] - 1) <= VOLUME_BAND
            chk("Comparable volume", vol_ok, f"Average daily {spec['driver_label']} changed by {((p['daily_driver'] / b['daily_driver'] - 1) * 100) if b['daily_driver'] else float('nan'):.1f}% between periods; within +/-{VOLUME_BAND:.0%} required so rates are comparable.")
            t = welch_t(b["daily_rates"], p["daily_rates"])
            chk("Change distinguishable from noise", t is not None and abs(t) >= MIN_T, "Welch t-statistic on daily cost rates is " + ("n/a (fewer than 7 days)" if t is None else f"{t:.2f}") + f"; |t| >= {MIN_T} required.")
            rel = (b["rate"] - p["rate"]) / b["rate"] if b["rate"] else 0
            chk("Material improvement", savings is not None and savings > 0 and rel >= MIN_REL_IMPROVEMENT, f"Cost rate changed by {rel:.1%}; an improvement of at least {MIN_REL_IMPROVEMENT:.0%} is required.")
            result["t_statistic"] = t
        chk("Assumptions documented", len((init.assumptions or "").strip()) >= 20, "Financial assumptions (at least 20 characters) must be recorded.")
        if not p:
            status = "forecast" if (init.expected_savings or 0) > 0 else "identified"
        else:
            status = "verified" if all(c["passed"] for c in checks) else "estimated"
    else:
        status = "forecast" if (init.expected_savings or 0) > 0 else "identified"
        chk("Baseline and post periods defined", False, "Define a baseline period, intervention date and post-intervention period to move beyond forecast.")

    init.calculated_savings = None if savings is None else money(savings)
    init.evidence_status = status
    result["checks"] = checks
    result["status"] = status
    result["calculated_savings"] = init.calculated_savings
    result["status_definitions"] = STATUS_TEXT
    result["required_evidence"] = REQUIRED
    result["caveat"] = (
        "Verified means the change versus baseline passed every evidence check above. It is not a controlled experiment; other changes in the same period could contribute."
        if status == "verified" else
        "This is an estimate, not proven causal savings: a reliable counterfactual (a long enough comparable baseline plus a distinguishable post-intervention change) has not been established."
        if status in ("estimated", "forecast") else "Opportunity only: nothing has been implemented or measured."
    )
    init.evidence_json = json.dumps(result, default=str)
    init.updated_at = datetime.utcnow()
    return result


STATUS_TEXT = {
    "identified": "Opportunity identified: a problem is quantified, nothing has been done.",
    "forecast": "Savings forecast: an expected saving is recorded, no post-intervention measurement exists yet.",
    "estimated": "Savings estimated after intervention: measured, but at least one evidence check failed.",
    "verified": "Savings verified: all evidence checks passed against a documented baseline.",
}
REQUIRED = [
    f"Baseline of at least {MIN_BASELINE_DAYS} days with >= {MIN_COVERAGE:.0%} data coverage, ending before the intervention date",
    f"Post-intervention period of at least {MIN_POST_DAYS} days with >= {MIN_COVERAGE:.0%} coverage",
    f"Comparable production volume (within +/-{VOLUME_BAND:.0%})",
    f"Statistically distinguishable change (|t| >= {MIN_T}) and at least {MIN_REL_IMPROVEMENT:.0%} improvement",
    "Documented financial assumptions",
]
