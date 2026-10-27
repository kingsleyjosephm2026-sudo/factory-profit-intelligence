"""Reproducible SIMULATED manufacturing dataset for a fictional company.

The same interval builder is used for the 90-day history (8-hour shift intervals) and for the live
simulation (15-minute intervals), so both obey identical coherence rules:

* units_produced = ideal_rate x run_minutes x performance      (run = period - planned - unplanned downtime)
* sum(downtime events, unplanned) == production_record.unplanned_downtime_min
* defective + good == units_produced; per-category defects sum to defective_units
* energy kWh follows run/idle time; material cost follows units produced; inventory usage follows line output

A few patterns are deliberately planted so the analytics have something to find (documented in
DATA_DICTIONARY.md): M-B2 bearing failures trending up, M-A3 electrical faults and an energy drift in the
last weeks, Line C night-shift defect growth, M-B4 material waste, a late Alloy Billet supplier, slow-moving
cartons and a PCB shortage at the end of the window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models as m

SHIFTS = [("A", 6), ("B", 14), ("C", 22)]
SHIFT_TARIFF = {"A": 6.8, "B": 8.4, "C": 5.6}  # currency per kWh (time-of-day tariff)
SHIFT_PERF = {"A": 0.94, "B": 0.93, "C": 0.89}
SHIFT_DT_MULT = {"A": 1.0, "B": 1.0, "C": 1.15}
LABOR_RATE = 230.0  # currency per labour hour
PLANNED_REASONS = {"CHANGEOVER", "PM_SCHEDULED", "CALIBRATION"}

FACTORY = {"name": "Meridian Components Pvt Ltd (fictional)", "location": "Bengaluru, India (simulated)", "currency": "INR"}
LINES = [("LA", "Line A - Injection Moulding"), ("LB", "Line B - CNC Machining"), ("LC", "Line C - Assembly & Test")]
MACHINES = [
    # code, name, line, rated units/h, kW, crew, unplanned events per 8h shift, mean event minutes, base defect rate
    ("M-A1", "Moulding Press A1", "LA", 240, 45, 2, 0.80, 20, 0.014),
    ("M-A2", "Moulding Press A2", "LA", 240, 45, 2, 0.80, 20, 0.016),
    ("M-A3", "Moulding Press A3", "LA", 180, 60, 2, 0.80, 22, 0.020),
    ("M-B1", "CNC Lathe B1", "LB", 90, 30, 2, 0.70, 22, 0.015),
    ("M-B2", "CNC Lathe B2", "LB", 90, 30, 2, 0.70, 24, 0.017),
    ("M-B3", "CNC Mill B3", "LB", 120, 38, 2, 0.70, 22, 0.018),
    ("M-B4", "CNC Mill B4", "LB", 120, 38, 2, 0.70, 22, 0.016),
    ("M-C1", "Assembly Cell C1", "LC", 60, 22, 3, 0.75, 18, 0.019),
    ("M-C2", "Assembly Cell C2", "LC", 60, 22, 3, 0.75, 18, 0.018),
    ("M-C3", "Test Station C3", "LC", 45, 35, 3, 0.75, 18, 0.017),
]
PRODUCTS = [
    # sku, name, category, line, price, std material, std conversion, speed factor
    ("P-A01", "Polymer Housing S", "Housings", "LA", 85, 28, 14, 1.0),
    ("P-A02", "Polymer Housing L", "Housings", "LA", 140, 52, 20, 0.8),
    ("P-A03", "Cable Clip", "Fittings", "LA", 18, 5, 3, 1.2),
    ("P-B01", "Steel Gear 40T", "Gears", "LB", 620, 240, 110, 1.0),
    ("P-B02", "Drive Shaft 12mm", "Shafts", "LB", 340, 130, 70, 1.1),
    ("P-B03", "Flange Plate", "Plates", "LB", 450, 190, 85, 0.9),
    ("P-C01", "Sensor Kit", "Kits", "LC", 960, 480, 150, 1.0),
    ("P-C02", "Control Module", "Modules", "LC", 1450, 760, 210, 0.85),
]
DEFECT_WEIGHTS = {
    "LA": {"Surface finish": 0.35, "Dimensional": 0.25, "Material defect": 0.25, "Other": 0.15},
    "LB": {"Dimensional": 0.55, "Surface finish": 0.25, "Material defect": 0.10, "Other": 0.10},
    "LC": {"Assembly fault": 0.50, "Other": 0.20, "Material defect": 0.20, "Dimensional": 0.10},
}
DEFAULT_REASONS = {
    "MECH_BEARING": 0.10, "MECH_BELT": 0.10, "ELEC_SENSOR": 0.14, "ELEC_POWER": 0.06, "MAT_SHORTAGE": 0.12,
    "JAM": 0.18, "OPER_ABSENCE": 0.08, "QUALITY_HOLD": 0.12, "TOOL_WEAR": 0.10,
}
# raw material items: code, name, line, unit cost, usage per unit produced, planned lead days, actual lead days, order cover days
INVENTORY_ITEMS = [
    ("RM-PP", "PP Granules (kg)", "LA", 95, 0.040, 4, 4, 14),
    ("RM-ABS", "ABS Masterbatch (kg)", "LA", 140, 0.010, 5, 5, 21),
    ("RM-STL", "Steel Bar 40mm (kg)", "LB", 78, 0.35, 4, 4, 14),
    ("RM-ALY", "Alloy Billet (kg)", "LB", 210, 0.18, 4, 9, 14),  # planted: supplier consistently late
    ("RM-PCB", "PCB Board (pcs)", "LC", 320, 1.0, 6, 6, 10),  # planted: late final replenishment
    ("RM-SNS", "Sensor Module (pcs)", "LC", 410, 1.0, 5, 5, 12),
    ("RM-CTN", "Packaging Carton (pcs)", "LC", 12, 0.2, 5, 5, 400),  # planted: slow-moving overstock
]


def shift_of(ts: datetime) -> str:
    h = ts.hour
    return "A" if 6 <= h < 14 else "B" if 14 <= h < 22 else "C"


# ----------------------------------------------------------------------------- planted patterns
def downtime_mult(code: str, t: float, shift: str) -> float:
    mult = SHIFT_DT_MULT[shift]
    if code == "M-B2":
        mult *= 2.2 * (1 + 0.9 * t)
    if code == "M-A3":
        mult *= 1.5
    return mult


def reason_weights(code: str) -> tuple[list[str], np.ndarray]:
    w = dict(DEFAULT_REASONS)
    if code == "M-B2":
        w["MECH_BEARING"] = 0.55
    if code == "M-A3":
        w["ELEC_SENSOR"] = 0.30
        w["ELEC_POWER"] = 0.25
    keys = list(w)
    p = np.array([w[k] for k in keys], dtype=float)
    return keys, p / p.sum()


def defect_rate(code: str, base: float, line: str, shift: str, t: float) -> float:
    rate = base
    if line == "LC" and shift == "C":
        rate += 0.004 + 0.022 * max(0.0, (t - 0.55) / 0.45)
    return rate


def energy_drift(code: str, t: float) -> float:
    return 1 + 0.22 * (t - 0.72) / 0.28 if code == "M-A3" and t > 0.72 else 1.0


def waste_fraction(code: str, rng: np.random.Generator) -> float:
    return max(0.0, rng.normal(0.015 + (0.025 if code == "M-B4" else 0.0), 0.006))


@dataclass
class Spec:
    lam: float
    dur: float
    defect: float


def spec_for(machine: m.Machine) -> Spec:
    for code, _n, _l, _r, _k, _c, lam, dur, defect in MACHINES:
        if code == machine.code:
            return Spec(lam, dur, defect)
    return Spec(0.75, 20.0, 0.018)  # imported machines get neutral behaviour in the live simulation


# ----------------------------------------------------------------------------- interval builder
def build_interval(machine, line_code, product, period_start, minutes, shift, t, rng, planned=None, cfg_target=0.85):
    """Return dict(prod, events, energy, quality, maintenance) for one machine and interval."""
    spec = spec_for(machine)
    planned = planned or []
    planned_down = float(sum(d for _r, d in planned))
    ideal_rate = machine.rated_units_per_hour * product.speed_factor

    events, maint = [], []
    off = 0.0
    for reason, dur in planned:
        events.append(dict(start_ts=period_start + timedelta(seconds=int(off * 60)), duration_min=float(dur), planned=True, reason_code=reason))
        if reason == "PM_SCHEDULED":
            maint.append(dict(event_ts=period_start, category="Preventive", duration_min=float(dur), cost=float(round(rng.uniform(1500, 4000), 2))))
        off += dur

    lam = spec.lam * downtime_mult(machine.code, t, shift) * minutes / 480.0
    n = int(rng.poisson(lam))
    keys, probs = reason_weights(machine.code)
    unpl = 0.0
    if n:
        durs = np.clip(rng.lognormal(math.log(spec.dur) - 0.18, 0.6, n), 3, 180)
        starts = np.sort(rng.uniform(planned_down, minutes, n))
        prev_end = planned_down
        for s, d in zip(starts, durs):
            s = max(float(s), prev_end + 1.0)
            d = round(min(float(d), minutes - s), 1)
            if d < 2:
                continue
            reason = str(rng.choice(keys, p=probs))
            events.append(dict(start_ts=period_start + timedelta(seconds=int(s * 60)), duration_min=d, planned=False, reason_code=reason))
            unpl += d
            prev_end = s + d
            if reason.startswith(("MECH", "ELEC")) and d >= 25:
                cat = "Corrective - Mechanical" if reason.startswith("MECH") else "Corrective - Electrical"
                maint.append(dict(event_ts=period_start + timedelta(seconds=int(s * 60)), category=cat, duration_min=d, cost=float(round(rng.uniform(2000, 15000), 2))))
    unpl = round(unpl, 1)
    run_min = max(0.0, minutes - planned_down - unpl)

    perf = float(np.clip(rng.normal(SHIFT_PERF[shift], 0.025), 0.80, 1.0))
    units = int(round(ideal_rate * run_min / 60 * perf))
    target = int(round(ideal_rate * (minutes - planned_down) / 60 * cfg_target))
    rate = defect_rate(machine.code, spec.defect, line_code, shift, t)
    defective = int(rng.binomial(units, min(max(rate, 0), 0.5))) if units > 0 else 0

    material_cost = round(units * float(product.std_material_cost) * (1 + waste_fraction(machine.code, rng)), 2)
    labor_hours = round(machine.crew_size * minutes / 60, 3)
    labor_cost = round(labor_hours * LABOR_RATE, 2)
    down_h = (planned_down + unpl) / 60
    load = float(rng.uniform(0.76, 0.88))
    kwh = machine.power_kw * (run_min / 60 * load + down_h * 0.12) * float(rng.normal(1.0, 0.03)) * energy_drift(machine.code, t)
    kwh = round(max(kwh, 0.0), 3)

    quality = []
    if defective:
        w = DEFECT_WEIGHTS[line_code]
        cats = list(w)
        counts = rng.multinomial(defective, np.array([w[c] for c in cats]) / sum(w.values()))
        quality = [(c, int(k)) for c, k in zip(cats, counts) if k > 0]

    prod = dict(
        machine_id=machine.id, product_id=product.id, period_start=period_start, period_minutes=minutes, shift=shift,
        planned_downtime_min=planned_down, unplanned_downtime_min=unpl, units_produced=units, defective_units=defective,
        target_units=target, material_cost=material_cost, labor_hours=labor_hours, labor_cost=labor_cost,
    )
    energy = dict(machine_id=machine.id, period_start=period_start, kwh=kwh, tariff=SHIFT_TARIFF[shift])
    return dict(prod=prod, events=events, energy=energy, quality=quality, maintenance=maint)


def persist_interval(db: Session, machine_id: int, built: dict, source: str) -> m.ProductionRecord:
    rec = m.ProductionRecord(**built["prod"], source=source)
    rec.quality = [m.QualityRecord(defect_category=c, defective_units=k) for c, k in built["quality"]]
    db.add(rec)
    for e in built["events"]:
        db.add(m.DowntimeEvent(machine_id=machine_id, source=source, **e))
    db.add(m.EnergyRecord(source=source, **built["energy"]))
    for e in built["maintenance"]:
        db.add(m.MaintenanceEvent(machine_id=machine_id, source=source, **e))
    return rec


# ----------------------------------------------------------------------------- reference + history
def create_reference(db: Session) -> None:
    if db.scalar(select(m.Factory.id)) is not None:
        return
    f = m.Factory(**FACTORY)
    db.add(f)
    db.flush()
    lines = {}
    for code, name in LINES:
        lines[code] = m.ProductionLine(factory_id=f.id, code=code, name=name)
        db.add(lines[code])
    db.flush()
    for code, name, line, rate, kw, crew, *_ in MACHINES:
        db.add(m.Machine(line_id=lines[line].id, code=code, name=name, rated_units_per_hour=rate, power_kw=kw, crew_size=crew))
    for sku, name, cat, _line, price, mat, conv, speed in PRODUCTS:
        db.add(m.Product(sku=sku, name=name, category=cat, unit_price=price, std_material_cost=mat, std_conversion_cost=conv, speed_factor=speed))
    db.flush()


def generate_history(db: Session, days: int = 90, end_date: date | None = None, seed: int = 42) -> dict:
    """Create reference data (if missing) and `days` days of history ending on `end_date` (default: yesterday)."""
    create_reference(db)
    rng = np.random.default_rng(seed)
    end = end_date or (date.today() - timedelta(days=1))
    start = end - timedelta(days=days - 1)

    machines = list(db.scalars(select(m.Machine).order_by(m.Machine.id)))
    lines = {ln.id: ln for ln in db.scalars(select(m.ProductionLine))}
    products = {p.sku: p for p in db.scalars(select(m.Product))}
    line_products: dict[str, list[m.Product]] = {}
    for sku, _n, _c, line, *_ in PRODUCTS:
        line_products.setdefault(line, []).append(products[sku])

    last_product: dict[int, int] = {}
    line_day_units: dict[tuple[str, date], int] = {}
    n_prod = 0
    for d in range(days):
        day = start + timedelta(days=d)
        t = d / max(days - 1, 1)
        for mi, mc in enumerate(machines):
            lc = lines[mc.line_id].code
            plist = line_products[lc]
            for si, (shift, hour) in enumerate(SHIFTS):
                prod = plist[(d // 2 + si + mi) % len(plist)]
                planned = []
                if mc.id in last_product and last_product[mc.id] != prod.id:
                    planned.append(("CHANGEOVER", float(20 + rng.integers(0, 16))))
                if (d + mi) % 7 == 0 and si == mi % 3:
                    planned.append(("PM_SCHEDULED", 60.0))
                if d % 30 == mi * 3 % 30 and si == 0:
                    planned.append(("CALIBRATION", 20.0))
                last_product[mc.id] = prod.id
                built = build_interval(mc, lc, prod, datetime.combine(day, time(hour)), 480, shift, t, rng, planned)
                persist_interval(db, mc.id, built, "demo")
                n_prod += 1
                key = (lc, day)
                line_day_units[key] = line_day_units.get(key, 0) + built["prod"]["units_produced"]
    db.flush()
    n_inv = _generate_inventory(db, lines, line_day_units, start, days, rng)
    db.commit()
    return {"start": start.isoformat(), "end": end.isoformat(), "production_records": n_prod, "inventory_rows": n_inv}


def _generate_inventory(db, lines, line_day_units, start: date, days: int, rng) -> int:
    line_by_code = {ln.code: ln for ln in lines.values()}
    count = 0
    for code, name, lc, cost, per_unit, lead_plan, lead_actual, cover in INVENTORY_ITEMS:
        usage = [line_day_units.get((lc, start + timedelta(days=d)), 0) * per_unit * float(rng.normal(1.0, 0.03)) for d in range(days)]
        avg0 = float(np.mean(usage[:14])) or 1.0
        reorder = avg0 * (lead_plan + 3)
        order_qty = avg0 * cover
        qty = reorder + order_qty * 0.6
        pending: list[tuple[int, float]] = []  # (arrival day index, quantity)
        for d in range(days):
            qty += sum(q for a, q in pending if a == d)
            pending = [(a, q) for a, q in pending if a != d]
            qty = max(0.0, qty - usage[d])
            if qty <= reorder and not pending:
                late = 6 if code == "RM-PCB" and d >= 80 else 0
                pending.append((d + lead_actual + late, order_qty))
            trailing = usage[max(0, d - 13): d + 1]
            db.add(m.InventorySnapshot(
                line_id=line_by_code[lc].id, item_code=code, item_name=name, snapshot_date=start + timedelta(days=d),
                quantity_on_hand=round(qty, 2), reorder_point=round(reorder, 2), unit_cost=cost,
                avg_daily_usage=round(float(np.mean(trailing)), 2), source="demo",
            ))
            count += 1
    return count


def wipe_all_data(db: Session, keep_reference: bool = True) -> None:
    """Delete transactional data (and optionally reference data). Used by `reset-db`."""
    for model in (m.QualityRecord, m.ProductionRecord, m.DowntimeEvent, m.EnergyRecord, m.InventorySnapshot,
                  m.MaintenanceEvent, m.Recommendation, m.SavingsInitiative, m.ImportLog):
        db.execute(delete(model))
    if not keep_reference:
        for model in (m.Machine, m.Product, m.ProductionLine, m.Factory):
            db.execute(delete(model))
    db.commit()
