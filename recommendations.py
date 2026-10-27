"""Deterministic, rules-based recommendation engine. No generative AI dependency.

Rules evaluate the most recent `window_days` of data, independent of UI filters, and are upserted by (rule_id, entity_key)
so user-set status and notes survive re-evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import Settings, get_settings
from .analytics import Filters, aggregate, data_bounds, inventory_status, load_frame
from .finance import money

WINDOW_DAYS = 30
RECENT_DAYS = 14


@dataclass
class Candidate:
    rule_id: str
    entity_key: str
    entity_type: str
    entity_name: str
    title: str
    evidence: str
    metric: str
    metric_value: float | None
    threshold: float | None
    severity: str
    next_action: str
    confidence: str
    calculation_method: str
    opportunity: float | None = None
    opportunity_basis: str = ""
    window: tuple = field(default_factory=tuple)


def evaluate_rules(db: Session, cfg: Settings | None = None, window_days: int = WINDOW_DAYS) -> list[Candidate]:
    cfg = cfg or get_settings()
    lo, hi = data_bounds(db)
    if hi is None:
        return []
    start = max(lo, hi - timedelta(days=window_days - 1))
    f = Filters(start, hi)
    df = load_frame(db, f, cfg)
    if df.empty:
        return []
    out: list[Candidate] = []
    out += _rule_downtime(df, cfg, f)
    out += _rule_defects(df, cfg, f)
    out += _rule_energy(db, cfg, hi, lo)
    out += _rule_inventory(db, cfg, f, hi)
    out += _rule_shift_gap(df, cfg, f)
    return out


def _conf(n: int, days: int) -> str:
    return "High" if n >= 20 and days >= 20 else "Medium" if n >= 8 else "Low"


def _rule_downtime(df, cfg, f) -> list[Candidate]:
    a = aggregate(df, ["machine_code", "machine_name"], cfg)
    ev_n = df.groupby("machine_code").size()
    median = float(a.unplanned_downtime_pct.median())
    thresh = max(6.0, 1.5 * median)
    res = []
    for _, r in a.iterrows():
        pct = r.unplanned_downtime_pct
        if pd.isna(pct) or pct < thresh:
            continue
        sev = "High" if pct >= 10 else "Medium"
        opp = money(r.avoid_downtime * cfg.realization_factor)
        res.append(Candidate(
            "downtime_high", r.machine_code, "machine", f"{r.machine_code} {r.machine_name}",
            f"Investigate unusually high unplanned downtime on {r.machine_code}",
            f"{r.machine_code} lost {pct:.1f}% of scheduled time to unplanned stops ({r.unpl_down:,.0f} min) vs a fleet median of {median:.1f}% "
            f"and a {cfg.benchmark_unplanned_downtime_pct:.0f}% benchmark, between {f.date_from} and {f.date_to}.",
            "unplanned_downtime_pct", round(float(pct), 2), round(thresh, 2), sev,
            "Review the top downtime reason codes for this machine, check maintenance history and spare-part condition, and schedule a root-cause review.",
            _conf(int(ev_n.get(r.machine_code, 0)), f.days),
            f"Trigger: unplanned downtime % >= max(6%, 1.5 x fleet median {median:.2f}%). Opportunity: avoidable downtime cost (cost above the "
            f"{cfg.benchmark_unplanned_downtime_pct:.0f}% benchmark) x realization factor {cfg.realization_factor:.0%}, for this {f.days}-day window.",
            opp, f"per {f.days}-day window", (f.date_from, f.date_to)))
    return res


def _rule_defects(df, cfg, f) -> list[Candidate]:
    overall = aggregate(df, None, cfg).iloc[0]
    a = aggregate(df, ["line_name", "shift"], cfg)
    res = []
    for _, r in a.iterrows():
        rate = r.defect_rate_pct
        if pd.isna(rate) or r.units < 1000:
            continue
        if rate >= 3.0 and rate >= 1.4 * overall.defect_rate_pct:
            sev = "High" if rate >= 4.0 else "Medium"
            opp = money(r.avoid_quality * cfg.realization_factor)
            res.append(Candidate(
                "defect_rate_high", f"{r.line_name}|{r["shift"]}", "line", f"{r.line_name}, shift {r['shift']}",
                f"Review elevated defect rate on {r.line_name}, shift {r["shift"]}",
                f"Defect rate of {rate:.2f}% ({int(r.defective):,} of {int(r.units):,} units) vs {overall.defect_rate_pct:.2f}% factory-wide "
                f"and a {cfg.benchmark_defect_rate_pct:.0f}% benchmark ({f.date_from} to {f.date_to}).",
                "defect_rate_pct", round(float(rate), 2), 3.0, sev,
                "Compare setup, tooling, operator practice and material lots against the other shifts; inspect the dominant defect category.",
                "High" if r.units >= 10000 else "Medium",
                "Trigger: defect rate >= 3.0% and >= 1.4 x the factory-wide rate. Opportunity: avoidable quality cost (above the 2% benchmark) x realization factor.",
                opp, f"per {f.days}-day window", (f.date_from, f.date_to)))
    return res


def _rule_energy(db, cfg, hi, lo) -> list[Candidate]:
    recent_start = hi - timedelta(days=RECENT_DAYS - 1)
    if (recent_start - lo).days < 14:
        return []
    df = load_frame(db, Filters(recent_start, hi), cfg)
    df = df[df.has_energy & df.base_kwh_unit.notna() & (df.units > 0)] if len(df) else df
    res = []
    if df.empty:
        return res
    df = df.assign(expected=df.base_kwh_unit * df.units)
    g = df.groupby(["machine_code", "machine_name"]).agg(kwh=("kwh", "sum"), expected=("expected", "sum"), units=("units", "sum"), loss=("loss_energy", "sum")).reset_index()
    for _, r in g.iterrows():
        ratio = r.kwh / r.expected - 1 if r.expected else 0
        if ratio >= 0.10 and r.units >= 1000:
            res.append(Candidate(
                "energy_excess", r.machine_code, "machine", f"{r.machine_code} {r.machine_name}",
                f"Investigate excess energy use per unit on {r.machine_code}",
                f"Over the last {RECENT_DAYS} days {r.machine_code} used {ratio:.1%} more energy than its own median kWh-per-unit baseline predicts "
                f"({r.kwh:,.0f} kWh vs {r.expected:,.0f} kWh expected for the same output).",
                "excess_kwh_ratio_pct", round(float(ratio * 100), 2), 10.0, "High" if ratio >= 0.2 else "Medium",
                "Check for mechanical friction, heater/compressor faults, leaks or changed process settings; verify with an energy audit.",
                "Medium",
                f"Trigger: last {RECENT_DAYS} days kWh >= 110% of (baseline kWh/unit x units). Opportunity: energy cost above a 5% tolerance x energy avoidable share "
                f"{cfg.energy_avoidable_share:.0%} x realization factor.",
                money(r.loss * cfg.energy_avoidable_share * cfg.realization_factor), f"per {RECENT_DAYS}-day window", (recent_start, hi)))
    return res


def _rule_inventory(db, cfg, f, hi) -> list[Candidate]:
    inv = inventory_status(db, Filters(hi - timedelta(days=WINDOW_DAYS - 1), hi), cfg)
    res = []
    for it in inv["items"]:
        if it["below_reorder"]:
            cover = it["days_of_cover"]
            sev = "High" if (cover is not None and cover < 3) or it["quantity_on_hand"] <= 0 else "Medium"
            res.append(Candidate(
                "inventory_below_reorder", it["item_code"], "item", f"{it['item_code']} {it['item_name']}",
                f"Review inventory below reorder point: {it['item_name']}",
                f"{it['quantity_on_hand']:,.0f} on hand vs a reorder point of {it['reorder_point']:,.0f}"
                + (f" ({cover:.1f} days of cover)" if cover is not None else "")
                + (f"; {it['stockout_days']} stockout day(s) in the window." if it["stockout_days"] else "."),
                "quantity_vs_reorder_point", it["quantity_on_hand"], it["reorder_point"], sev,
                "Confirm open purchase orders, expedite with the supplier if lead time slipped, and review the reorder point against actual lead time.",
                "High", "Trigger: latest quantity on hand < reorder point. No financial opportunity is claimed (risk is availability, not cost).", None, "", (f.date_from, f.date_to)))
        if it["slow_moving"]:
            res.append(Candidate(
                "inventory_slow_moving", it["item_code"], "item", f"{it['item_code']} {it['item_name']}",
                f"Review slow-moving stock: {it['item_name']}",
                f"{it['days_of_cover']:.0f} days of cover (threshold {cfg.slow_moving_days_cover:.0f}); carrying cost in the window is {it['carrying_cost']:,.0f} {cfg.currency}.",
                "days_of_cover", it["days_of_cover"], cfg.slow_moving_days_cover, "Low",
                "Reduce order quantity or frequency and check for obsolete demand.", "Medium",
                f"Trigger: days of cover > {cfg.slow_moving_days_cover:.0f}. Opportunity: carrying cost of stock above {cfg.max_days_cover:.0f} days of usage x realization factor.",
                money(it["avoidable_carrying_cost"] * cfg.realization_factor), f"per {WINDOW_DAYS}-day window", (f.date_from, f.date_to)))
    return res


def _rule_shift_gap(df, cfg, f) -> list[Candidate]:
    a = aggregate(df, ["line_name", "shift"], cfg)
    res = []
    for line, g in a.groupby("line_name"):
        g = g[g.units > 1000]
        if len(g) < 2:
            continue
        best, worst = g.loc[g.efficiency_pct.idxmax()], g.loc[g.efficiency_pct.idxmin()]
        gap = best.efficiency_pct - worst.efficiency_pct
        if gap < 5.0:
            continue
        cm = float((df[(df.line_name == line)].eval("cm_unit * ideal_units").sum()) / df[(df.line_name == line)].ideal_units.sum())
        recoverable_units = (gap / 100) * worst.ideal_units * 0.5
        res.append(Candidate(
            "shift_efficiency_gap", f"{line}", "line", str(line), f"Compare shift efficiency on {line}",
            f"Output efficiency on shift {worst['shift']} is {worst.efficiency_pct:.1f}% vs {best.efficiency_pct:.1f}% on shift {best['shift']} (gap {gap:.1f} points).",
            "efficiency_gap_pts", round(float(gap), 2), 5.0, "High" if gap >= 8 else "Medium",
            "Observe both shifts for a week: staffing, changeover practice, material availability and escalation response times.", "Medium",
            "Trigger: best-minus-worst shift output efficiency >= 5 points on the same line. Opportunity: close 50% of the gap on the weakest shift x average contribution margin x realization factor.",
            money(recoverable_units * cm * cfg.realization_factor), f"per {f.days}-day window", (f.date_from, f.date_to)))
    return res


def refresh(db: Session, cfg: Settings | None = None) -> dict:
    """Evaluate rules and upsert. Existing status/notes are preserved."""
    cfg = cfg or get_settings()
    cands = evaluate_rules(db, cfg)
    now = datetime.utcnow()
    existing = {(r.rule_id, r.entity_key): r for r in db.scalars(select(m.Recommendation))}
    seen, created = set(), 0
    for c in cands:
        key = (c.rule_id, c.entity_key)
        seen.add(key)
        row = existing.get(key)
        fields = dict(entity_type=c.entity_type, entity_name=c.entity_name, title=c.title, evidence=c.evidence, metric=c.metric,
                      metric_value=c.metric_value, threshold=c.threshold, severity=c.severity, next_action=c.next_action,
                      estimated_opportunity=c.opportunity, opportunity_basis=c.opportunity_basis, confidence=c.confidence,
                      calculation_method=c.calculation_method, window_start=c.window[0] if c.window else None, window_end=c.window[1] if c.window else None)
        if row is None:
            db.add(m.Recommendation(rule_id=c.rule_id, entity_key=c.entity_key, status="Open", notes="", active=True, created_at=now, last_evaluated_at=now, updated_at=now, **fields))
            created += 1
        else:
            for k, v in fields.items():
                setattr(row, k, v)
            row.active, row.last_evaluated_at = True, now
    deactivated = 0
    for key, row in existing.items():
        if key not in seen and row.active:
            row.active = False
            row.last_evaluated_at = now
            deactivated += 1
    db.commit()
    return dict(evaluated=len(cands), created=created, updated=len(seen) - created, deactivated=deactivated)
