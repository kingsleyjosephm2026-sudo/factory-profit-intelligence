"""Analytics engine: loads filtered data into pandas, applies the transparent loss model, aggregates."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import Settings, get_settings
from .finance import money

LOSS_CATS = ["downtime", "quality", "energy", "material"]
CAT_LABEL = {"downtime": "Downtime impact", "quality": "Quality-related cost", "energy": "Excess energy",
             "material": "Material waste", "inventory": "Inventory carrying cost"}


# ----------------------------------------------------------------------------- filters
@dataclass(frozen=True)
class Filters:
    date_from: date
    date_to: date
    line_id: int | None = None
    machine_id: int | None = None
    product_id: int | None = None
    shift: str | None = None

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def previous(self) -> "Filters":
        n = self.days
        return replace(self, date_from=self.date_from - timedelta(days=n), date_to=self.date_from - timedelta(days=1))

    @property
    def inventory_eligible(self) -> bool:
        return self.machine_id is None and self.product_id is None and self.shift is None


def data_bounds(db: Session) -> tuple[date | None, date | None]:
    lo, hi = db.execute(select(func.min(m.ProductionRecord.period_start), func.max(m.ProductionRecord.period_start))).one()
    if lo is None:
        return None, None
    lo, hi = _to_dt(lo), _to_dt(hi)
    return lo.date(), hi.date()


def _to_dt(v: Any) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def default_filters(db: Session, days: int = 30, **kw) -> Filters:
    lo, hi = data_bounds(db)
    if hi is None:
        today = date.today()
        return Filters(today, today, **kw)
    return Filters(max(lo, hi - timedelta(days=days - 1)), hi, **kw)


def _clauses(f: Filters) -> list:
    c = [m.ProductionRecord.period_start >= datetime.combine(f.date_from, time.min),
         m.ProductionRecord.period_start < datetime.combine(f.date_to + timedelta(days=1), time.min)]
    if f.line_id is not None:
        c.append(m.Machine.line_id == f.line_id)
    if f.machine_id is not None:
        c.append(m.ProductionRecord.machine_id == f.machine_id)
    if f.product_id is not None:
        c.append(m.ProductionRecord.product_id == f.product_id)
    if f.shift is not None:
        c.append(m.ProductionRecord.shift == f.shift)
    return c


def production_select():
    P, M, L, R, E = m.ProductionRecord, m.Machine, m.ProductionLine, m.Product, m.EnergyRecord
    return (
        select(
            P.id.label("id"), P.period_start, P.period_minutes, P.shift, P.planned_downtime_min.label("planned_down"),
            P.unplanned_downtime_min.label("unpl_down"), P.units_produced.label("units"), P.defective_units.label("defective"),
            P.target_units.label("target"), P.material_cost, P.labor_hours, P.labor_cost, P.source,
            M.id.label("machine_id"), M.code.label("machine_code"), M.name.label("machine_name"), M.line_id,
            M.rated_units_per_hour.label("rated_rate"), L.code.label("line_code"), L.name.label("line_name"),
            R.id.label("product_id"), R.sku.label("product_sku"), R.name.label("product_name"), R.category,
            R.unit_price, R.std_material_cost.label("std_mat"), R.std_conversion_cost.label("std_conv"), R.speed_factor,
            E.kwh, E.tariff,
        )
        .select_from(P)
        .join(M, M.id == P.machine_id).join(L, L.id == M.line_id).join(R, R.id == P.product_id)
        .outerjoin(E, and_(E.machine_id == P.machine_id, E.period_start == P.period_start))
    )


NUMERIC_COLS = ["period_minutes", "planned_down", "unpl_down", "units", "defective", "target", "material_cost", "labor_hours",
                "labor_cost", "rated_rate", "unit_price", "std_mat", "std_conv", "speed_factor", "kwh", "tariff"]


def energy_baselines(db: Session) -> pd.DataFrame:
    """Median kWh per unit per machine+product over ALL loaded history (not filter dependent)."""
    P, E = m.ProductionRecord, m.EnergyRecord
    stmt = (select(P.machine_id, P.product_id, P.units_produced.label("units"), E.kwh)
            .join(E, and_(E.machine_id == P.machine_id, E.period_start == P.period_start)).where(P.units_produced > 0))
    df = pd.read_sql(stmt, db.connection())
    if df.empty:
        return pd.DataFrame(columns=["machine_id", "product_id", "base_kwh_unit"])
    df["kpu"] = df.kwh / df.units
    mp = df.groupby(["machine_id", "product_id"]).agg(base_kwh_unit=("kpu", "median"), n=("kpu", "size")).reset_index()
    mach = df.groupby("machine_id")["kpu"].median().rename("mach_base").reset_index()
    mp = mp.merge(mach, on="machine_id")
    mp["base_kwh_unit"] = np.where(mp.n >= 10, mp.base_kwh_unit, mp.mach_base)
    return mp[["machine_id", "product_id", "base_kwh_unit"]]


def load_frame(db: Session, f: Filters, cfg: Settings | None = None) -> pd.DataFrame:
    cfg = cfg or get_settings()
    df = pd.read_sql(production_select().where(*_clauses(f)).order_by(m.ProductionRecord.period_start), db.connection())
    return enrich(df, energy_baselines(db), cfg)


def sdiv(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)


def enrich(df: pd.DataFrame, base: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    df = df.copy()
    df["period_start"] = pd.to_datetime(df["period_start"])
    for c in NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["has_energy"] = df["kwh"].notna()
    df["kwh"] = df["kwh"].fillna(0.0)
    df["tariff"] = df["tariff"].fillna(0.0)
    df["date"] = df["period_start"].dt.normalize()
    df["good"] = df["units"] - df["defective"]
    df["ideal_rate"] = df["rated_rate"] * df["speed_factor"]
    df["cm_unit"] = df["unit_price"] - df["std_mat"] - df["std_conv"]
    df["energy_cost"] = df["kwh"] * df["tariff"]
    df["run_min"] = (df["period_minutes"] - df["planned_down"] - df["unpl_down"]).clip(lower=0)
    df["ideal_units"] = df["ideal_rate"] * df["period_minutes"] / 60
    df["lost_units"] = df["unpl_down"] / 60 * df["ideal_rate"]

    df = df.merge(base, on=["machine_id", "product_id"], how="left")
    df["loss_downtime"] = df["lost_units"] * df["cm_unit"] * cfg.downtime_unrecoverable_share
    df["loss_quality"] = df["defective"] * (df["std_mat"] + df["std_conv"]) * (1 - cfg.scrap_salvage_rate)
    allowed = df["base_kwh_unit"] * df["units"] * (1 + cfg.energy_tolerance_pct / 100)
    df["excess_kwh"] = np.where(df["has_energy"] & df["base_kwh_unit"].notna(), (df["kwh"] - allowed).clip(lower=0), 0.0)
    df["loss_energy"] = df["excess_kwh"] * df["tariff"]
    df["loss_material"] = (df["material_cost"] - df["units"] * df["std_mat"] * (1 + cfg.material_allowance_pct / 100)).clip(lower=0)

    # avoidable share per machine, from explicit benchmarks
    if len(df):
        g = df.groupby("machine_id")
        unpl_tot = g["unpl_down"].transform("sum")
        per_tot = g["period_minutes"].transform("sum")
        r_dt = pd.Series(1 - cfg.benchmark_unplanned_downtime_pct / 100 * per_tot / unpl_tot.replace(0, np.nan), index=df.index).clip(lower=0).fillna(0)
        def_tot = g["defective"].transform("sum")
        units_tot = g["units"].transform("sum")
        r_q = pd.Series(1 - cfg.benchmark_defect_rate_pct / 100 * units_tot / def_tot.replace(0, np.nan), index=df.index).clip(lower=0).fillna(0)
    else:
        r_dt = r_q = pd.Series(dtype=float)
    df["avoid_downtime"] = df["loss_downtime"] * r_dt
    df["avoid_quality"] = df["loss_quality"] * r_q
    df["avoid_energy"] = df["loss_energy"] * cfg.energy_avoidable_share
    df["avoid_material"] = df["loss_material"] * cfg.material_avoidable_share
    return df


# ----------------------------------------------------------------------------- aggregation helpers
SUM_COLS = ["units", "good", "defective", "target", "unpl_down", "planned_down", "period_minutes", "run_min", "ideal_units", "kwh",
            "energy_cost", "lost_units", "material_cost", "labor_cost"] + [f"loss_{c}" for c in LOSS_CATS] + [f"avoid_{c}" for c in LOSS_CATS]


def aggregate(df: pd.DataFrame, by: list[str] | None, cfg: Settings | None = None) -> pd.DataFrame:
    cfg = cfg or get_settings()
    cols = [c for c in SUM_COLS if c in df.columns]
    if df.empty:
        out = pd.DataFrame(columns=(by or []) + cols)
    elif by:
        out = df.groupby(by, dropna=False)[cols].sum().reset_index()
    else:
        out = pd.DataFrame([df[cols].sum()])
    return derive(out, cfg)


def derive(a: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    if a.empty:
        for c in ["defect_rate_pct", "target_attainment_pct", "unplanned_downtime_pct", "kwh_per_good_unit", "efficiency_pct",
                  "observed_loss", "avoidable_cost", "potential_savings"]:
            a[c] = pd.Series(dtype=float)
        return a
    a = a.copy()
    a["defect_rate_pct"] = sdiv(a["defective"], a["units"]) * 100
    a["target_attainment_pct"] = sdiv(a["units"], a["target"]) * 100
    a["unplanned_downtime_pct"] = sdiv(a["unpl_down"], a["period_minutes"]) * 100
    a["kwh_per_good_unit"] = sdiv(a["kwh"], a["good"])
    a["efficiency_pct"] = sdiv(a["units"], a["ideal_units"]) * 100
    a["observed_loss"] = sum(a[f"loss_{c}"] for c in LOSS_CATS)
    a["avoidable_cost"] = sum(a[f"avoid_{c}"] for c in LOSS_CATS)
    a["potential_savings"] = a["avoidable_cost"] * cfg.realization_factor
    return a


def records(df: pd.DataFrame, round_to: int = 4) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN -> None, numpy -> python, datetimes -> iso)."""
    out = []
    for row in df.to_dict("records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, (pd.Timestamp, datetime)):
                v = v.isoformat()
            elif isinstance(v, date):
                v = v.isoformat()
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating, float)):
                v = None if (v is None or math.isnan(v) or math.isinf(v)) else round(float(v), round_to)
            elif isinstance(v, np.bool_):
                v = bool(v)
            clean[k] = v
        out.append(clean)
    return out


def scalar(a: pd.DataFrame, col: str) -> float | None:
    if a.empty or col not in a:
        return None
    v = a.iloc[0][col]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


# ----------------------------------------------------------------------------- inventory
def inventory_frame(db: Session, f: Filters) -> pd.DataFrame:
    S, L = m.InventorySnapshot, m.ProductionLine
    stmt = (select(S.id, S.line_id, L.name.label("line_name"), S.item_code, S.item_name, S.snapshot_date, S.quantity_on_hand.label("qty"),
                   S.reorder_point, S.unit_cost, S.avg_daily_usage).join(L, L.id == S.line_id)
            .where(S.snapshot_date >= f.date_from, S.snapshot_date <= f.date_to))
    if f.line_id is not None:
        stmt = stmt.where(S.line_id == f.line_id)
    df = pd.read_sql(stmt, db.connection())
    if not df.empty:
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    return df


def inventory_costs(inv: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    """Per snapshot-day carrying cost and avoidable (above max-days-cover) carrying cost."""
    if inv.empty:
        return inv.assign(carrying=[], avoid_carrying=[])
    inv = inv.copy()
    daily = cfg.carrying_rate_annual / 365
    inv["carrying"] = inv["qty"] * inv["unit_cost"] * daily
    max_level = inv["avg_daily_usage"] * cfg.max_days_cover
    inv["avoid_carrying"] = (inv["qty"] - max_level).clip(lower=0) * inv["unit_cost"] * daily
    return inv


def inventory_summary(db: Session, f: Filters, cfg: Settings) -> dict:
    inv = inventory_costs(inventory_frame(db, f), cfg)
    if inv.empty or not f.inventory_eligible:
        return {"observed": 0.0, "avoidable": 0.0, "by_line": {}, "applicable": f.inventory_eligible}
    by_line = inv.groupby("line_name")[["carrying", "avoid_carrying"]].sum()
    return {"observed": float(inv.carrying.sum()), "avoidable": float(inv.avoid_carrying.sum()),
            "by_line": {k: {"observed": float(v.carrying), "avoidable": float(v.avoid_carrying)} for k, v in by_line.iterrows()},
            "applicable": True}


def inventory_status(db: Session, f: Filters, cfg: Settings | None = None) -> dict:
    cfg = cfg or get_settings()
    inv = inventory_costs(inventory_frame(db, f), cfg)
    if inv.empty:
        return {"items": [], "summary": {"items": 0, "breaches": 0, "stockout_days": 0, "slow_moving": 0, "carrying_cost": 0.0, "avoidable_carrying_cost": 0.0}}
    items = []
    for code, g in inv.sort_values("snapshot_date").groupby("item_code"):
        last = g.iloc[-1]
        cover = (last.qty / last.avg_daily_usage) if last.avg_daily_usage > 0 else None
        stock_days = int((g.qty <= 0).sum())
        items.append(dict(
            item_code=code, item_name=last.item_name, line_name=last.line_name, as_of=last.snapshot_date.date().isoformat(),
            quantity_on_hand=round(float(last.qty), 1), reorder_point=round(float(last.reorder_point), 1),
            days_of_cover=None if cover is None else round(float(cover), 1), below_reorder=bool(last.qty < last.reorder_point),
            stockout_days=stock_days, slow_moving=bool(cover is not None and cover > cfg.slow_moving_days_cover),
            stock_value=money(last.qty * last.unit_cost), carrying_cost=money(g.carrying.sum()), avoidable_carrying_cost=money(g.avoid_carrying.sum()),
        ))
    summ = dict(items=len(items), breaches=sum(i["below_reorder"] for i in items), stockout_days=sum(i["stockout_days"] for i in items),
                slow_moving=sum(i["slow_moving"] for i in items), carrying_cost=money(inv.carrying.sum()),
                avoidable_carrying_cost=money(inv.avoid_carrying.sum()))
    return {"items": items, "summary": summ}


# ----------------------------------------------------------------------------- loss analysis
def loss_summary(db: Session, f: Filters, cfg: Settings | None = None, df: pd.DataFrame | None = None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg) if df is None else df
    a = aggregate(df, None, cfg)
    inv = inventory_summary(db, f, cfg)
    cats = []
    for c in LOSS_CATS:
        obs = scalar(a, f"loss_{c}") or 0.0
        av = scalar(a, f"avoid_{c}") or 0.0
        cats.append(dict(category=c, label=CAT_LABEL[c], observed=money(obs), avoidable=money(av), potential=money(av * cfg.realization_factor)))
    cats.append(dict(category="inventory", label=CAT_LABEL["inventory"], observed=money(inv["observed"]), avoidable=money(inv["avoidable"]),
                     potential=money(inv["avoidable"] * cfg.realization_factor)))
    cats.sort(key=lambda r: r["observed"], reverse=True)
    tot_obs = money(sum(c["observed"] for c in cats))
    tot_av = money(sum(c["avoidable"] for c in cats))
    tot_pot = money(sum(c["potential"] for c in cats))
    return dict(
        categories=cats,
        totals=dict(observed=tot_obs, avoidable=tot_av, potential=tot_pot),
        currency=cfg.currency, inventory_applicable=inv["applicable"],
        note=("Observed cost is what the loss model attributes to each category. Estimated avoidable cost is the part above explicit benchmarks. "
              "Potential future savings applies a realization factor and is NOT verified profit."),
    )


def loss_breakdown(db: Session, f: Filters, by: str, grain: str = "day", cfg: Settings | None = None) -> list[dict]:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    key = {"machine": ["machine_code", "machine_name", "line_name"], "line": ["line_id", "line_name"], "product": ["product_sku", "product_name", "category"],
           "shift": ["shift"], "date": ["bucket"]}[by]
    if by == "date":
        df = df.assign(bucket=bucket(df["date"], grain))
    a = aggregate(df, key, cfg)
    if by == "line":
        inv = inventory_summary(db, f, cfg)
        a["inventory_observed"] = a["line_name"].map(lambda n: inv["by_line"].get(n, {}).get("observed", 0.0))
        a["inventory_avoidable"] = a["line_name"].map(lambda n: inv["by_line"].get(n, {}).get("avoidable", 0.0))
        a["observed_loss"] += a["inventory_observed"]
        a["avoidable_cost"] += a["inventory_avoidable"]
        a["potential_savings"] = a["avoidable_cost"] * cfg.realization_factor
    a = a.sort_values("bucket" if by == "date" else "observed_loss", ascending=by == "date")
    keep = key + ["units", "defect_rate_pct", "unplanned_downtime_pct", "kwh_per_good_unit", "target_attainment_pct"] + [f"loss_{c}" for c in LOSS_CATS] + \
           (["inventory_observed"] if by == "line" else []) + ["observed_loss", "avoidable_cost", "potential_savings"]
    out = a[keep]
    for c in [c for c in out.columns if c.startswith("loss_") or c in ("observed_loss", "avoidable_cost", "potential_savings", "inventory_observed")]:
        out[c] = out[c].map(money)
    return records(out)


def bucket(dates: pd.Series, grain: str) -> pd.Series:
    d = pd.to_datetime(dates)
    if grain == "week":
        return (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.date.astype(str)
    if grain == "month":
        return d.dt.to_period("M").dt.start_time.dt.date.astype(str)
    return d.dt.date.astype(str)


def trend(df: pd.DataFrame, grain: str, cfg: Settings | None = None) -> pd.DataFrame:
    cfg = cfg or get_settings()
    if df.empty:
        return aggregate(df, ["bucket"], cfg)
    a = aggregate(df.assign(bucket=bucket(df["date"], grain)), ["bucket"], cfg)
    return a.sort_values("bucket")


# ----------------------------------------------------------------------------- dashboard
def _pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def summary_cards(db: Session, f: Filters, cfg: Settings | None = None) -> dict:
    cfg = cfg or get_settings()
    cur_df, prev_df = load_frame(db, f, cfg), load_frame(db, f.previous(), cfg)
    cur, prev = aggregate(cur_df, None, cfg), aggregate(prev_df, None, cfg)
    cur_loss, prev_loss = loss_summary(db, f, cfg, cur_df), loss_summary(db, f.previous(), cfg, prev_df)
    open_high = db.scalar(select(func.count()).select_from(m.Recommendation).where(m.Recommendation.status == "Open", m.Recommendation.severity == "High")) or 0

    def card(key, label, c, p, unit, better, definition_key, digits=2):
        diff = None if (c is None or p is None) else round(c - p, digits)
        return dict(key=key, label=label, value=None if c is None else round(c, digits), previous=None if p is None else round(p, digits), unit=unit,
                    abs_diff=diff, pct_diff=_pct_change(c, p), better=better, definition_key=definition_key)

    cards = [
        card("units", "Total production", scalar(cur, "units") or 0, scalar(prev, "units") if len(prev_df) else None, "units", "higher", "total_units", 0),
        card("good", "Good units", scalar(cur, "good") or 0, scalar(prev, "good") if len(prev_df) else None, "units", "higher", "good_units", 0),
        card("defect", "Defect rate", scalar(cur, "defect_rate_pct"), scalar(prev, "defect_rate_pct"), "%", "lower", "defect_rate"),
        card("downtime", "Unplanned downtime", scalar(cur, "unpl_down") or 0, scalar(prev, "unpl_down") if len(prev_df) else None, "min", "lower", "unplanned_downtime", 0),
        card("energy", "Energy cost", money(scalar(cur, "energy_cost") or 0), money(scalar(prev, "energy_cost")) if len(prev_df) else None, cfg.currency, "lower", "energy_cost"),
        card("loss", "Estimated operational loss", cur_loss["totals"]["observed"], prev_loss["totals"]["observed"] if len(prev_df) else None, cfg.currency, "lower", "loss_downtime"),
        card("attainment", "Target attainment", scalar(cur, "target_attainment_pct"), scalar(prev, "target_attainment_pct"), "%", "higher", "target_attainment"),
        dict(key="recs", label="Open high-priority recommendations", value=int(open_high), previous=None, unit="", abs_diff=None, pct_diff=None, better="lower", definition_key=None),
    ]
    return dict(filters=_fdict(f), previous_period=dict(date_from=f.previous().date_from.isoformat(), date_to=f.previous().date_to.isoformat()),
                cards=cards, currency=cfg.currency, records=int(len(cur_df)))


def _fdict(f: Filters) -> dict:
    return dict(date_from=f.date_from.isoformat(), date_to=f.date_to.isoformat(), line_id=f.line_id, machine_id=f.machine_id, product_id=f.product_id, shift=f.shift)


def dashboard_charts(db: Session, f: Filters, grain: str = "day", cfg: Settings | None = None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    t = trend(df, grain, cfg)
    ls = loss_summary(db, f, cfg, df)
    by_line = loss_breakdown(db, f, "line", cfg=cfg)
    by_machine = loss_breakdown(db, f, "machine", cfg=cfg)[:5]
    cols = lambda names: records(t[["bucket"] + names]) if not t.empty else []  # noqa: E731
    return dict(
        grain=grain,
        production_vs_target=cols(["units", "target"]),
        loss_by_category=ls["categories"], loss_totals=ls["totals"],
        downtime_trend=cols(["unpl_down", "planned_down", "unplanned_downtime_pct"]),
        defect_trend=cols(["defect_rate_pct", "defective", "units"]),
        energy_trend=cols(["kwh", "energy_cost", "kwh_per_good_unit"]),
        loss_by_line=by_line, top_machines=by_machine,
    )


# ----------------------------------------------------------------------------- domain analytics
def production_analytics(db: Session, f: Filters, grain: str = "day", cfg=None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    cols = ["units", "good", "defective", "target", "target_attainment_pct", "efficiency_pct"]
    out = dict(totals=records(aggregate(df, None, cfg)[cols])[0] if len(df) else None, trend=records(trend(df, grain, cfg)[["bucket"] + cols]))
    for name, key in [("by_machine", ["machine_code", "machine_name"]), ("by_line", ["line_name"]), ("by_product", ["product_sku", "product_name"]), ("by_shift", ["shift"])]:
        out[name] = records(aggregate(df, key, cfg)[key + cols]) if len(df) else []
    return out


def event_frame(db: Session, f: Filters) -> pd.DataFrame:
    E, M, L = m.DowntimeEvent, m.Machine, m.ProductionLine
    stmt = (select(E.id, E.start_ts, E.duration_min, E.planned, E.reason_code, M.id.label("machine_id"), M.code.label("machine_code"), M.line_id, L.name.label("line_name"))
            .join(M, M.id == E.machine_id).join(L, L.id == M.line_id)
            .where(E.start_ts >= datetime.combine(f.date_from, time.min), E.start_ts < datetime.combine(f.date_to + timedelta(days=1), time.min)))
    if f.line_id is not None:
        stmt = stmt.where(M.line_id == f.line_id)
    if f.machine_id is not None:
        stmt = stmt.where(E.machine_id == f.machine_id)
    df = pd.read_sql(stmt, db.connection())
    if not df.empty:
        df["start_ts"] = pd.to_datetime(df["start_ts"])
        df["shift"] = np.where((df.start_ts.dt.hour >= 6) & (df.start_ts.dt.hour < 14), "A", np.where((df.start_ts.dt.hour >= 14) & (df.start_ts.dt.hour < 22), "B", "C"))
        if f.shift is not None:
            df = df[df["shift"] == f.shift]
    return df


def downtime_analytics(db: Session, f: Filters, grain: str = "day", cfg=None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    ev = event_frame(db, f)
    a = aggregate(df, ["machine_id", "machine_code", "machine_name"], cfg)
    unpl = ev[~ev.planned.astype(bool)] if len(ev) else ev
    plan = ev[ev.planned.astype(bool)] if len(ev) else ev
    machines = []
    for _, r in a.iterrows():
        mu = unpl[unpl.machine_id == r.machine_id] if len(unpl) else unpl
        n = int(len(mu))
        run_h = float(r.run_min) / 60
        machines.append(dict(machine_code=r.machine_code, machine_name=r.machine_name, unplanned_minutes=round(float(r.unpl_down), 1),
                             planned_minutes=round(float(r.planned_down), 1), unplanned_pct=None if math.isnan(r.unplanned_downtime_pct) else round(float(r.unplanned_downtime_pct), 2),
                             events=n, mtbf_hours=round(run_h / n, 2) if n >= 3 else None,
                             mttr_minutes=round(float(mu.duration_min.mean()), 1) if n >= 3 else None,
                             lost_units=round(float(r.lost_units), 0), impact=money(r.loss_downtime)))
    machines.sort(key=lambda r: r["impact"], reverse=True)

    def pareto(frame):
        if frame is None or frame.empty:
            return []
        g = frame.groupby("reason_code").agg(minutes=("duration_min", "sum"), events=("id", "size")).reset_index().sort_values("minutes", ascending=False)
        g["cum_pct"] = g.minutes.cumsum() / g.minutes.sum() * 100
        return records(g)

    tr = trend(df, grain, cfg)
    return dict(
        totals=dict(unplanned_minutes=round(float(df.unpl_down.sum()), 1), planned_minutes=round(float(df.planned_down.sum()), 1),
                    unplanned_events=int(len(unpl)), planned_events=int(len(plan)), impact=money(df.loss_downtime.sum())),
        by_machine=machines, reasons_unplanned=pareto(unpl), reasons_planned=pareto(plan),
        trend=records(tr[["bucket", "unpl_down", "planned_down", "unplanned_downtime_pct"]]) if len(tr) else [],
        note="Planned downtime (changeover, preventive maintenance, calibration) is shown separately and excluded from loss. Event views ignore the product filter.",
    )


def quality_analytics(db: Session, f: Filters, grain: str = "day", cfg=None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    Q, P, M = m.QualityRecord, m.ProductionRecord, m.Machine
    stmt = (select(Q.defect_category, func.sum(Q.defective_units).label("units")).join(P, P.id == Q.production_record_id).join(M, M.id == P.machine_id)
            .where(*_clauses(f)).group_by(Q.defect_category))
    cats = [dict(category=c, units=int(u)) for c, u in db.execute(stmt).all()]
    cats.sort(key=lambda r: r["units"], reverse=True)
    tot = sum(c["units"] for c in cats) or 0
    for c in cats:
        c["share_pct"] = round(c["units"] / tot * 100, 1) if tot else None
    tr = trend(df, grain, cfg)
    cols = ["units", "defective", "defect_rate_pct", "loss_quality"]
    out = dict(totals=records(aggregate(df, None, cfg)[cols + ["good"]])[0] if len(df) else None, categories=cats,
               trend=records(tr[["bucket"] + cols]) if len(tr) else [],
               first_pass_yield_pct=None if df.empty or df.units.sum() == 0 else round(float(df.good.sum() / df.units.sum() * 100), 2),
               note="No rework data is captured, so first-pass yield equals overall yield (100% - defect rate).")
    for name, key in [("by_machine", ["machine_code"]), ("by_line", ["line_name"]), ("by_product", ["product_sku", "product_name"]), ("by_shift", ["shift"])]:
        out[name] = records(aggregate(df, key, cfg)[key + cols]) if len(df) else []
    return out


def energy_analytics(db: Session, f: Filters, grain: str = "day", cfg=None) -> dict:
    cfg = cfg or get_settings()
    df = load_frame(db, f, cfg)
    df = df[df.has_energy] if len(df) else df
    cols = ["kwh", "energy_cost", "kwh_per_good_unit", "loss_energy"]
    tr = trend(df, grain, cfg)
    abn = []
    if len(df):
        d2 = df[(df.units > 0) & df.base_kwh_unit.notna()].copy()
        d2["kwh_per_unit"] = d2.kwh / d2.units
        d2["ratio"] = d2.kwh_per_unit / d2.base_kwh_unit
        top = d2[d2.ratio > 1.15].sort_values("loss_energy", ascending=False).head(15)
        abn = records(top[["id", "period_start", "machine_code", "product_sku", "shift", "kwh", "kwh_per_unit", "base_kwh_unit", "ratio", "loss_energy"]], 3)
        flagged = int((d2.ratio > 1.15).sum())
    else:
        flagged = 0
    return dict(
        totals=records(aggregate(df, None, cfg)[cols])[0] if len(df) else None, trend=records(tr[["bucket"] + cols]) if len(tr) else [],
        by_line=records(aggregate(df, ["line_name"], cfg)[["line_name"] + cols]) if len(df) else [],
        by_machine=records(aggregate(df, ["machine_code"], cfg)[["machine_code"] + cols]) if len(df) else [],
        abnormal=dict(threshold_ratio=1.15, flagged_records=flagged, top=abn,
                      definition="Interval kWh per unit more than 15% above that machine+product's median kWh per unit."),
    )


# ----------------------------------------------------------------------------- record listings (paginated)
def paginate(stmt, db: Session, page: int, page_size: int, count_stmt=None) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).mappings().all()
    return dict(total=int(total or 0), page=page, page_size=page_size, items=[_jsonrow(r) for r in rows])


def _jsonrow(r) -> dict:
    out = {}
    for k, v in dict(r).items():
        out[k] = v.isoformat() if isinstance(v, (datetime, date)) else v
    return out
