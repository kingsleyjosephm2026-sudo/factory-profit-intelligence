"""Loads the operational tables into pandas DataFrames and applies user filters.

The merged hourly "fact" frame is cached per (database, data_version) - a single-process cache
that is invalidated whenever any write bumps `simulation_state.data_version`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.settings_store import get_assumptions
from app.db import models as m
from app.db.session import get_engine
from app.db.version import get_version


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    factories: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    machines: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    shifts: list[str] = field(default_factory=list)

    def key(self) -> tuple:
        return (self.date_from, self.date_to, tuple(self.factories), tuple(self.lines), tuple(self.machines), tuple(self.products), tuple(self.shifts))


@dataclass
class Frames:
    version: int
    assumptions: dict[str, Any]
    fact: pd.DataFrame            # hourly production + energy + quality aggregates + dims + loss columns
    downtime: pd.DataFrame        # downtime events + dims
    maintenance: pd.DataFrame
    quality: pd.DataFrame         # quality records + dims (period_start, machine, line, product ...)
    inventory: pd.DataFrame       # daily snapshots (+ loss columns)
    machines: pd.DataFrame
    products: pd.DataFrame
    energy_baseline: dict[str, dict[str, float]]
    min_date: date | None
    max_date: date | None


_CACHE: dict[str, Frames] = {}


def _f(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float)


def _read(session: Session, stmt) -> pd.DataFrame:
    return pd.read_sql(stmt, session.connection())


def build_frames(session: Session) -> Frames:
    from app.analytics.loss import compute_inventory_loss, compute_loss_rows

    version = get_version(session)
    A = get_assumptions(session)

    mach = _read(session, select(m.Machine.id.label("machine_id"), m.Machine.code.label("machine"), m.Machine.name.label("machine_name"), m.Machine.machine_type,
                                 m.Machine.rated_kw, m.Machine.idle_kw, m.ProductionLine.code.label("line"), m.ProductionLine.name.label("line_name"),
                                 m.Factory.code.label("factory")).join(m.ProductionLine, m.Machine.line_id == m.ProductionLine.id).join(m.Factory, m.ProductionLine.factory_id == m.Factory.id))
    prod = _read(session, select(m.Product.id.label("product_id"), m.Product.sku, m.Product.name.label("product_name"), m.Product.category, m.Product.selling_price.label("price"),
                                 m.Product.bom_kg_per_unit.label("bom"), m.Product.material_cost_per_kg.label("mat_cost_kg"), m.Product.std_conversion_cost.label("conv_cost"),
                                 m.Product.rework_cost, m.Product.target_defect_rate_pct.label("target_def_pct"), m.Product.material_code))
    for c in ["rated_kw", "idle_kw"]:
        mach[c] = _f(mach[c])
    for c in ["price", "bom", "mat_cost_kg", "conv_cost", "rework_cost", "target_def_pct"]:
        prod[c] = _f(prod[c])
    prod["mat_cost_unit"] = prod["bom"] * prod["mat_cost_kg"]
    prod["cm_unit"] = prod["price"] - prod["mat_cost_unit"] - prod["conv_cost"]

    pr = _read(session, select(m.ProductionRecord.id.label("prod_id"), m.ProductionRecord.machine_id, m.ProductionRecord.product_id, m.ProductionRecord.period_start,
                               m.ProductionRecord.shift, m.ProductionRecord.planned_minutes, m.ProductionRecord.planned_downtime_minutes.label("planned_dt"),
                               m.ProductionRecord.unplanned_downtime_minutes.label("unplanned_dt"), m.ProductionRecord.run_minutes, m.ProductionRecord.ideal_cycle_time_sec,
                               m.ProductionRecord.target_units, m.ProductionRecord.units_produced.label("units"), m.ProductionRecord.good_units.label("good"),
                               m.ProductionRecord.defective_units.label("defective"), m.ProductionRecord.material_kg_used.label("material_kg"), m.ProductionRecord.labor_hours,
                               m.ProductionRecord.labor_cost, m.ProductionRecord.source))
    en = _read(session, select(m.EnergyRecord.machine_id, m.EnergyRecord.period_start, m.EnergyRecord.kwh, m.EnergyRecord.tariff_per_kwh.label("tariff"), m.EnergyRecord.energy_cost))
    q = _read(session, select(m.QualityRecord.id.label("quality_id"), m.QualityRecord.production_record_id.label("prod_id"), m.QualityRecord.defect_category,
                              m.QualityRecord.defect_units, m.QualityRecord.scrapped_units, m.QualityRecord.reworked_units))
    for c in ["target_units", "ideal_cycle_time_sec", "material_kg", "labor_hours", "labor_cost"]:
        pr[c] = _f(pr[c])
    pr["period_start"] = pd.to_datetime(pr["period_start"])
    en["period_start"] = pd.to_datetime(en["period_start"])
    for c in ["kwh", "tariff", "energy_cost"]:
        en[c] = _f(en[c])

    qa = q.groupby("prod_id").agg(scrapped=("scrapped_units", "sum"), reworked=("reworked_units", "sum")).reset_index() if len(q) else pd.DataFrame(columns=["prod_id", "scrapped", "reworked"])
    fact = pr.merge(mach, on="machine_id", how="left").merge(prod, on="product_id", how="left").merge(en, on=["machine_id", "period_start"], how="left").merge(qa, on="prod_id", how="left")
    for c in ["kwh", "tariff", "energy_cost", "scrapped", "reworked"]:
        fact[c] = fact[c].fillna(0.0)
    fact["day"] = fact["period_start"].dt.normalize()
    fact["hour"] = fact["period_start"].dt.hour
    fact = fact.sort_values(["machine", "period_start"]).reset_index(drop=True)

    qd = q.merge(fact[["prod_id", "period_start", "day", "machine", "line", "sku", "category", "shift"]], on="prod_id", how="left") if len(q) else pd.DataFrame(
        columns=["quality_id", "prod_id", "defect_category", "defect_units", "scrapped_units", "reworked_units", "period_start", "day", "machine", "line", "sku", "category", "shift"])

    dt = _read(session, select(m.DowntimeEvent.id.label("event_id"), m.DowntimeEvent.machine_id, m.DowntimeEvent.start_ts, m.DowntimeEvent.end_ts, m.DowntimeEvent.duration_minutes,
                               m.DowntimeEvent.planned, m.DowntimeEvent.reason_code, m.DowntimeEvent.reason_category, m.DowntimeEvent.description, m.DowntimeEvent.source))
    dt["duration_minutes"] = _f(dt["duration_minutes"])
    dt["start_ts"] = pd.to_datetime(dt["start_ts"])
    dt["end_ts"] = pd.to_datetime(dt["end_ts"])
    dt["planned"] = dt["planned"].astype(bool)
    dt = dt.merge(mach[["machine_id", "machine", "line", "line_name", "factory"]], on="machine_id", how="left")
    dt["day"] = dt["start_ts"].dt.normalize()

    mt = _read(session, select(m.MaintenanceEvent.id.label("maint_id"), m.MaintenanceEvent.machine_id, m.MaintenanceEvent.event_ts, m.MaintenanceEvent.category, m.MaintenanceEvent.description,
                               m.MaintenanceEvent.duration_minutes, m.MaintenanceEvent.cost, m.MaintenanceEvent.planned))
    mt["cost"] = _f(mt["cost"])
    mt["duration_minutes"] = _f(mt["duration_minutes"])
    mt["event_ts"] = pd.to_datetime(mt["event_ts"])
    mt = mt.merge(mach[["machine_id", "machine", "line"]], on="machine_id", how="left")

    inv = _read(session, select(m.InventorySnapshot.id.label("inv_id"), m.InventorySnapshot.snapshot_date, m.InventorySnapshot.item_code, m.InventorySnapshot.item_name,
                                m.InventorySnapshot.item_type, m.InventorySnapshot.product_id, m.InventorySnapshot.qty_on_hand, m.InventorySnapshot.unit, m.InventorySnapshot.unit_cost,
                                m.InventorySnapshot.reorder_point, m.InventorySnapshot.max_level, m.InventorySnapshot.daily_usage))
    for c in ["qty_on_hand", "unit_cost", "reorder_point", "max_level", "daily_usage"]:
        inv[c] = _f(inv[c])
    inv["snapshot_date"] = pd.to_datetime(inv["snapshot_date"])
    inv["day"] = inv["snapshot_date"].dt.normalize()
    inv = inv.merge(prod[["product_id", "sku", "category"]], on="product_id", how="left").sort_values(["item_code", "snapshot_date"]).reset_index(drop=True)

    fact, baseline = compute_loss_rows(fact, A)
    inv = compute_inventory_loss(inv, A)

    min_d = fact["day"].min().date() if len(fact) else None
    max_d = fact["day"].max().date() if len(fact) else None
    return Frames(version, A, fact, dt, mt, qd, inv, mach, prod, baseline, min_d, max_d)


def get_frames(session: Session) -> Frames:
    """Cached frames; rebuilt when the data version (or database) changes."""
    key = str(get_engine().url)
    ver = get_version(session)
    cached = _CACHE.get(key)
    if cached is not None and cached.version == ver:
        return cached
    # a read transaction may already be open; frames are built from a consistent snapshot
    fr = build_frames(session)
    _CACHE.clear()
    _CACHE[key] = fr
    return fr


def clear_cache() -> None:
    _CACHE.clear()


# ----------------------------------------------------------------------------- filtering

def _isin(series: pd.Series, values: list[str]) -> pd.Series:
    return series.isin(values) if values else pd.Series(True, index=series.index)


def apply_filters(df: pd.DataFrame, f: Filters, date_col: str = "day", skip: tuple[str, ...] = ()) -> pd.DataFrame:
    """Filter any frame carrying the relevant dimension columns (missing columns are ignored)."""
    mask = pd.Series(True, index=df.index)
    if f.date_from is not None and date_col in df:
        mask &= df[date_col] >= pd.Timestamp(f.date_from)
    if f.date_to is not None and date_col in df:
        mask &= df[date_col] <= pd.Timestamp(f.date_to)
    if "factory" in df and "factory" not in skip:
        mask &= _isin(df["factory"], f.factories)
    if "line" in df and "line" not in skip:
        mask &= _isin(df["line"], f.lines)
    if "machine" in df and "machine" not in skip:
        mask &= _isin(df["machine"], f.machines)
    if "sku" in df and "sku" not in skip:
        mask &= _isin(df["sku"], f.products)
    if "shift" in df and "shift" not in skip:
        mask &= _isin(df["shift"], f.shifts)
    return df[mask]


def previous_period(f: Filters, fr: Frames) -> Filters:
    """Same filters shifted back by the selected period length (default: the full data range)."""
    start = f.date_from or fr.min_date
    end = f.date_to or fr.max_date
    if start is None or end is None:
        return Filters(factories=f.factories, lines=f.lines, machines=f.machines, products=f.products, shifts=f.shifts)
    n = (end - start).days + 1
    return Filters(date_from=start - timedelta(days=n), date_to=start - timedelta(days=1), factories=f.factories, lines=f.lines, machines=f.machines,
                   products=f.products, shifts=f.shifts)


def resolve_period(f: Filters, fr: Frames) -> Filters:
    """Fill in an open date range with the data range."""
    return Filters(date_from=f.date_from or fr.min_date, date_to=f.date_to or fr.max_date, factories=f.factories, lines=f.lines, machines=f.machines,
                   products=f.products, shifts=f.shifts)
