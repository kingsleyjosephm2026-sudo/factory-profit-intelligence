"""Hourly machine simulator shared by the history generator and the live demo simulator.

Everything produced here is SIMULATED. The relationships are deliberately coherent so the
analytics have something real to find:

* Unplanned failures follow an hourly hazard that rises with days since the last
  preventive maintenance (PM) and is higher on the night shift.
* Tool/process wear also raises the defect probability with days since PM.
* The two hours after an unplanned stop have lower speed and a higher defect probability
  ("restart effect").
* Energy follows run minutes (load) plus idle load during stops, with a time-of-day tariff.
* Material consumption follows units produced x BOM plus a process-waste fraction.

Embedded, documented "stories" (all fictional) that the analytics can discover:
  PRS-201  recurring hydraulic leaks; a hose/seal replacement on STORY_INTERVENTION_DAY cuts them.
  CNC-102  PM skipped for ~30 days -> rising defects and failures (maintenance-overdue story).
  WLD-203  elevated kWh for a spell (and a smaller lasting increase afterwards).
  PRS-202  die wear raises process material waste from day 40.
  Night shift (C) slightly slower with more defects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

PLANT = {
    "code": "PLANT-01",
    "name": "Meridian Components Pvt Ltd - Plant 1 (FICTIONAL, SIMULATED)",
    "location": "Fictional industrial estate",
    "timezone": "Asia/Kolkata",
    "currency": "INR",
}

LINES = [("L1", "Machining Line"), ("L2", "Pressing & Welding Line"), ("L3", "Assembly & Packaging Line")]

MATERIALS = {
    "MAT-STEEL-BAR": {"name": "Steel bar stock", "unit_cost": 78.0},
    "MAT-STEEL-SHEET": {"name": "Steel sheet coil", "unit_cost": 72.0},
    "MAT-ASSY-PA": {"name": "Pump assembly components (blended)", "unit_cost": 410.0},
    "MAT-KIT-VK": {"name": "Valve kit components (blended)", "unit_cost": 520.0},
}

PRODUCT_DEFS: list[dict[str, Any]] = [
    dict(sku="SH-100", name="Shaft Housing SH-100", category="Housings", line="L1", price=1450, material="MAT-STEEL-BAR", bom=2.4, conv=210, rework=120, target_def=1.5, cycle=90),
    dict(sku="GB-200", name="Gear Blank GB-200", category="Machined Parts", line="L1", price=620, material="MAT-STEEL-BAR", bom=0.9, conv=95, rework=55, target_def=1.2, cycle=45),
    dict(sku="MB-300", name="Mounting Bracket MB-300", category="Brackets", line="L2", price=240, material="MAT-STEEL-SHEET", bom=0.55, conv=38, rework=18, target_def=2.0, cycle=12),
    dict(sku="CP-400", name="Chassis Panel CP-400", category="Panels", line="L2", price=760, material="MAT-STEEL-SHEET", bom=2.8, conv=120, rework=70, target_def=1.8, cycle=30),
    dict(sku="PA-500", name="Pump Assembly PA-500", category="Assemblies", line="L3", price=3900, material="MAT-ASSY-PA", bom=3.1, conv=520, rework=350, target_def=1.5, cycle=150),
    dict(sku="VK-600", name="Valve Kit VK-600", category="Assemblies", line="L3", price=1850, material="MAT-KIT-VK", bom=1.2, conv=260, rework=160, target_def=1.4, cycle=75),
]

# code, name, line, type, rated_kw, idle_kw, speed, crew, products, hazard/hour, perf mean
MACHINE_DEFS: list[tuple] = [
    ("CNC-101", "CNC Machining Centre 101", "L1", "CNC", 45, 8, 1.00, 1, ["SH-100", "GB-200"], 0.032, 0.91),
    ("CNC-102", "CNC Machining Centre 102", "L1", "CNC", 45, 8, 1.02, 1, ["SH-100", "GB-200"], 0.032, 0.91),
    ("CNC-103", "CNC Machining Centre 103", "L1", "CNC", 48, 8, 0.98, 1, ["SH-100", "GB-200"], 0.034, 0.90),
    ("LTH-104", "CNC Lathe 104", "L1", "Lathe", 30, 5, 1.00, 1, ["GB-200", "SH-100"], 0.028, 0.92),
    ("PRS-201", "Hydraulic Press 201", "L2", "Press", 160, 25, 1.00, 2, ["MB-300", "CP-400"], 0.052, 0.90),
    ("PRS-202", "Hydraulic Press 202", "L2", "Press", 155, 24, 1.03, 2, ["MB-300", "CP-400"], 0.032, 0.91),
    ("WLD-203", "Robotic Welding Cell 203", "L2", "Welder", 70, 12, 1.00, 2, ["CP-400", "MB-300"], 0.033, 0.91),
    ("ASM-301", "Assembly Station 301", "L3", "Assembly", 18, 4, 1.00, 3, ["PA-500", "VK-600"], 0.030, 0.90),
    ("ASM-302", "Assembly Station 302", "L3", "Assembly", 18, 4, 1.04, 3, ["PA-500", "VK-600"], 0.030, 0.90),
    ("PKG-303", "Packaging & Test Cell 303", "L3", "Packaging", 12, 3, 1.00, 2, ["VK-600", "PA-500"], 0.026, 0.93),
]

REASON_WEIGHTS: dict[str, dict[str, float]] = {
    "CNC": {"MECH-BRG": .14, "ELEC-SNS": .14, "ELEC-DRV": .10, "TOOL-BRK": .30, "MAT-SHT": .08, "QC-HOLD": .10, "OPR-ERR": .10, "UTL-PWR": .04},
    "Lathe": {"MECH-BRG": .14, "ELEC-SNS": .14, "ELEC-DRV": .10, "TOOL-BRK": .30, "MAT-SHT": .08, "QC-HOLD": .10, "OPR-ERR": .10, "UTL-PWR": .04},
    "Press": {"MECH-HYD": .22, "MECH-BRG": .10, "ELEC-SNS": .10, "ELEC-DRV": .08, "TOOL-BRK": .20, "MAT-SHT": .10, "QC-HOLD": .08, "OPR-ERR": .08, "UTL-PWR": .04},
    "Welder": {"ELEC-SNS": .25, "ELEC-DRV": .12, "TOOL-BRK": .15, "MAT-SHT": .10, "QC-HOLD": .14, "OPR-ERR": .14, "UTL-PWR": .10},
    "Assembly": {"ELEC-SNS": .20, "MAT-SHT": .22, "QC-HOLD": .16, "OPR-ERR": .28, "MECH-BRG": .04, "UTL-PWR": .10},
    "Packaging": {"ELEC-SNS": .25, "MAT-SHT": .25, "OPR-ERR": .25, "MECH-BRG": .10, "UTL-PWR": .15},
}
DURATION_MEDIAN_MIN = {"MECH-BRG": 150, "MECH-HYD": 95, "ELEC-SNS": 40, "ELEC-DRV": 55, "TOOL-BRK": 35, "MAT-SHT": 120, "QC-HOLD": 45, "OPR-ERR": 20, "UTL-PWR": 25}
CORRECTIVE_COST = {"MECH-BRG": 28000, "MECH-HYD": 14000, "ELEC-SNS": 6500, "ELEC-DRV": 11000, "TOOL-BRK": 9000}
CORRECTIVE_TEXT = {
    "MECH-BRG": "Replace bearing / spindle component",
    "MECH-HYD": "Repair hydraulic leak, top up and bleed circuit",
    "ELEC-SNS": "Replace or re-seat sensor / reset PLC",
    "ELEC-DRV": "Reset and inspect drive / VFD",
    "TOOL-BRK": "Replace broken tool or die insert",
}

DEFECT_WEIGHTS: dict[str, dict[str, float]] = {
    "CNC": {"Dimensional": .55, "Surface finish": .30, "Material flaw": .15},
    "Lathe": {"Dimensional": .55, "Surface finish": .30, "Material flaw": .15},
    "Press": {"Dimensional": .35, "Surface finish": .25, "Material flaw": .40},
    "Welder": {"Weld defect": .60, "Dimensional": .20, "Surface finish": .20},
    "Assembly": {"Assembly fit": .60, "Material flaw": .15, "Surface finish": .25},
    "Packaging": {"Packaging damage": .60, "Assembly fit": .40},
}
SCRAP_PROB = {"Dimensional": .70, "Surface finish": .40, "Weld defect": .30, "Assembly fit": .20, "Material flaw": .95, "Packaging damage": .10}

SHIFT_PERF = {"A": 1.0, "B": 0.985, "C": 0.955}
SHIFT_DEF = {"A": 1.0, "B": 1.0, "C": 1.30}
SHIFT_HAZ = {"A": 1.0, "B": 1.0, "C": 1.20}
WAGE = {"A": 240.0, "B": 250.0, "C": 285.0}  # currency per labour hour
WEAR_DEFECT_PER_DAY = 0.030
WEAR_HAZARD_PER_DAY = 0.040
RESTART_PERF = 0.93
RESTART_DEFECT = 1.9
TARGET_EFFICIENCY = 0.88   # production target = ideal rate x available planned time x 88 %


@dataclass
class SimConfig:
    start_date: date = date(2026, 7, 1)
    days: int = 92
    pm_skip_window: tuple[int, int] = (45, 75)       # CNC-102 PM skipped between these day indexes
    story_intervention_day: int = 62                 # PRS-201 hose/seal replacement
    wld_energy_window: tuple[int, int] = (50, 61)
    tariff_revision_day: int = 45
    prs202_waste_day: int = 40
    starvation_days: tuple[int, ...] = (63, 64)      # forced MAT-SHT stops on line L2 (steel sheet disruption)

    def day_idx(self, ts: datetime) -> int:
        return (ts.date() - self.start_date).days


@dataclass
class MachineSpec:
    idx: int
    code: str
    name: str
    line: str
    mtype: str
    rated_kw: float
    idle_kw: float
    speed: float
    crew: int
    products: list[str]
    hazard: float
    perf: float


def machine_specs() -> list[MachineSpec]:
    return [MachineSpec(i, *d) for i, d in enumerate(MACHINE_DEFS)]


@dataclass
class MState:
    last_pm_ts: datetime
    last_product: str | None = None
    stop: dict | None = None
    pending: list[dict] = field(default_factory=list)
    restart_hours: int = 0

    def to_json(self) -> dict:
        stop = None
        if self.stop:
            stop = {**self.stop, "start": self.stop["start"].isoformat(), "end": self.stop["end"].isoformat()}
        return {"last_pm_ts": self.last_pm_ts.isoformat(), "last_product": self.last_product, "stop": stop, "pending": self.pending, "restart_hours": self.restart_hours}

    @staticmethod
    def from_json(d: dict) -> "MState":
        stop = d.get("stop")
        if stop:
            stop = {**stop, "start": datetime.fromisoformat(stop["start"]), "end": datetime.fromisoformat(stop["end"])}
        return MState(datetime.fromisoformat(d["last_pm_ts"]), d.get("last_product"), stop, list(d.get("pending") or []), int(d.get("restart_hours") or 0))


def shift_of(ts: datetime) -> str:
    h = ts.hour
    return "A" if 6 <= h < 14 else ("B" if 14 <= h < 22 else "C")


def is_idle_hour(ts: datetime) -> bool:
    """Plant is idle for the production day starting Sunday 06:00 (Sun 06:00 -> Mon 06:00)."""
    return (ts - timedelta(hours=6)).weekday() == 6


def tariff_for(ts: datetime, cfg: SimConfig) -> float:
    h = ts.hour
    base = 6.8 if h < 6 else (8.6 if h < 18 else (10.8 if h < 22 else 7.2))
    if cfg.day_idx(ts) >= cfg.tariff_revision_day:
        base *= 1.04
    return round(base, 3)


def product_for(spec: MachineSpec, ts: datetime) -> str:
    pday = (ts - timedelta(hours=6)).date().toordinal()
    return spec.products[((pday // 3) + spec.idx) % len(spec.products)]


def _pm_item(spec: MachineSpec, ts: datetime, cfg: SimConfig) -> dict | None:
    """Weekly planned-maintenance slot, deterministic in (machine, timestamp)."""
    if ts.minute != 0 or ts.weekday() != spec.idx % 6 or ts.hour != 13 + spec.idx % 3:
        return None
    di = cfg.day_idx(ts)
    if spec.code == "CNC-102" and cfg.pm_skip_window[0] <= di <= cfg.pm_skip_window[1]:
        return None  # story: preventive maintenance overdue
    k = (ts.date().toordinal() // 7 + spec.idx) % 5
    if k == 0:
        return {"reason": "CAL", "minutes": 60, "maint": "calibration", "desc": f"Calibration of {spec.code}", "cost": 4500, "resets_pm": True}
    if k == 1:
        return {"reason": "PM-SCH", "minutes": 75, "maint": "predictive", "desc": f"Condition-based inspection of {spec.code}", "cost": 5200, "resets_pm": True}
    return {"reason": "PM-SCH", "minutes": 100, "maint": "preventive", "desc": f"Scheduled preventive maintenance of {spec.code}", "cost": 7500, "resets_pm": True}


def _forced_items(spec: MachineSpec, ts: datetime, cfg: SimConfig) -> list[dict]:
    di = cfg.day_idx(ts)
    out: list[dict] = []
    if spec.code == "PRS-201" and di == cfg.story_intervention_day and ts.hour == 8 and ts.minute == 0:
        out.append({"reason": "PM-SCH", "minutes": 180, "maint": "corrective", "desc": "INTERVENTION: replace hydraulic hoses and seals on PRS-201", "cost": 85000, "resets_pm": True, "planned": True})
    if spec.line == "L2" and di in cfg.starvation_days and ts.hour == 9 and ts.minute == 0:
        out.append({"reason": "MAT-SHT", "minutes": 105 + 10 * spec.idx % 40, "maint": None, "desc": "Steel sheet coil not available (supplier delay)", "cost": 0, "resets_pm": False, "planned": False})
    return out


def _weights_for(spec: MachineSpec, di: int, cfg: SimConfig) -> tuple[dict[str, float], float]:
    base = dict(REASON_WEIGHTS[spec.mtype])
    if spec.code == "PRS-201":
        base["MECH-HYD"] = 0.50
    total0 = sum(base.values())
    adj = dict(base)
    if spec.code == "PRS-201" and di >= cfg.story_intervention_day:
        adj["MECH-HYD"] *= 0.30
    return adj, sum(adj.values()) / total0


def _round_money(x: float) -> float:
    return float(round(x, 2))


def step_hour(spec: MachineSpec, ts: datetime, st: MState, rng: np.random.Generator, cfg: SimConfig, products: dict[str, dict]) -> dict[str, Any]:
    """Advance one machine by one hour and return the records for that hour."""
    di = cfg.day_idx(ts)
    shift = shift_of(ts)
    sku = product_for(spec, ts)
    prod = products[sku]

    pm = _pm_item(spec, ts, cfg)
    if pm:
        st.pending.append(pm)
    st.pending.extend(_forced_items(spec, ts, cfg))
    if st.last_product is not None and st.last_product != sku:
        st.pending.append({"reason": "CHG-OVR", "minutes": int(rng.integers(30, 51)), "maint": None, "desc": f"Changeover {st.last_product} -> {sku}", "cost": 0, "resets_pm": False})
    st.last_product = sku

    new_stops: list[dict] = []
    new_maint: list[dict] = []
    segments: list[tuple[int, int, bool]] = []

    free_from = 0
    if st.stop is not None and st.stop["end"] > ts:
        end_min = int(math.ceil((st.stop["end"] - ts).total_seconds() / 60.0))
        free_from = min(60, end_min)
        segments.append((0, free_from, bool(st.stop["planned"])))
    ended_unplanned = bool(st.stop is not None and not st.stop["planned"] and st.stop["end"] <= ts + timedelta(hours=1) and st.stop["end"] > ts)

    dsp = max(0.0, (ts - st.last_pm_ts).total_seconds() / 86400.0)
    if free_from < 60:
        item = None
        if st.pending:
            item = st.pending.pop(0)
            start_min = free_from
            planned = bool(item.get("planned", item["reason"] in ("PM-SCH", "CAL", "CHG-OVR")))
        else:
            weights, scale = _weights_for(spec, di, cfg)
            p_fail = spec.hazard * (1.0 + WEAR_HAZARD_PER_DAY * dsp) * SHIFT_HAZ[shift] * scale
            if rng.random() < min(p_fail, 0.5):
                codes = list(weights)
                probs = np.array([weights[c] for c in codes], dtype=float)
                reason = str(rng.choice(codes, p=probs / probs.sum()))
                dur = float(np.clip(DURATION_MEDIAN_MIN[reason] * math.exp(rng.normal(0, 0.6)), 5, 600))
                item = {"reason": reason, "minutes": int(round(dur)), "maint": "corrective" if reason in CORRECTIVE_COST else None,
                        "desc": CORRECTIVE_TEXT.get(reason) or f"Unplanned stop: {reason}",
                        "cost": CORRECTIVE_COST.get(reason, 0), "resets_pm": False}
                start_min = int(rng.integers(free_from, 60))
                planned = False
        if item is not None:
            start = ts + timedelta(minutes=start_min)
            end = start + timedelta(minutes=int(item["minutes"]))
            st.stop = {"start": start, "end": end, "reason": item["reason"], "planned": planned}
            segments.append((start_min, min(60, start_min + int(item["minutes"])), planned))
            new_stops.append({"start_ts": start, "end_ts": end, "duration_minutes": int(item["minutes"]), "planned": planned, "reason_code": item["reason"], "description": item["desc"]})
            if item.get("maint"):
                fixed_cost = "INTERVENTION" in item["desc"]
                cost = float(item["cost"]) if fixed_cost else float(item["cost"]) * float(math.exp(rng.normal(0, 0.15)))
                new_maint.append({"event_ts": start, "category": item["maint"], "description": item["desc"], "duration_minutes": int(item["minutes"]),
                                  "cost": _round_money(cost), "planned": bool(planned or fixed_cost), "link": (start, item["reason"])})
            if item.get("resets_pm"):
                st.last_pm_ts = start
            if not planned and end <= ts + timedelta(hours=1):
                ended_unplanned = True

    planned_dt = sum(e - s for s, e, pl in segments if pl)
    unplanned_dt = sum(e - s for s, e, pl in segments if not pl)
    planned_dt = int(min(planned_dt, 60))
    unplanned_dt = int(min(unplanned_dt, 60 - planned_dt))
    run_min = 60 - planned_dt - unplanned_dt

    restart = st.restart_hours > 0 or ended_unplanned
    st.restart_hours = 2 if ended_unplanned else max(0, st.restart_hours - 1)

    ideal_cycle = prod["cycle"] / spec.speed
    ideal_uph = 3600.0 / ideal_cycle
    perf = float(np.clip(rng.normal(spec.perf, 0.03) * SHIFT_PERF[shift] * (RESTART_PERF if restart else 1.0), 0.55, 1.0))
    units = int(round(ideal_uph * run_min / 60.0 * perf)) if run_min > 0 else 0
    target = round(ideal_uph * (60 - planned_dt) / 60.0 * TARGET_EFFICIENCY, 2)

    p_def = prod["target_def"] / 100.0 * 0.85 * (1 + WEAR_DEFECT_PER_DAY * dsp) * SHIFT_DEF[shift] * (RESTART_DEFECT if restart else 1.0)
    defective = int(rng.binomial(units, min(p_def, 0.5))) if units > 0 else 0
    good = units - defective

    quality: list[dict] = []
    if defective > 0:
        dw = DEFECT_WEIGHTS[spec.mtype]
        cats = list(dw)
        split = rng.multinomial(defective, np.array([dw[c] for c in cats]) / sum(dw.values()))
        for cat, n in zip(cats, split):
            n = int(n)
            if n <= 0:
                continue
            scrapped = int(rng.binomial(n, SCRAP_PROB[cat]))
            quality.append({"defect_category": cat, "defect_units": n, "scrapped_units": scrapped, "reworked_units": n - scrapped})

    waste_base = 0.008
    if spec.code == "PRS-202" and di >= cfg.prs202_waste_day:
        waste_base = 0.022
    waste = waste_base * float(math.exp(rng.normal(0, 0.2)))
    material_kg = round(units * prod["bom"] * (1 + waste), 3)

    kwh = spec.rated_kw * run_min / 60.0 * float(rng.uniform(0.94, 1.06)) + spec.idle_kw * (60 - run_min) / 60.0 * 0.9
    if spec.code == "WLD-203":
        if cfg.wld_energy_window[0] <= di <= cfg.wld_energy_window[1]:
            kwh *= 1.22
        elif di > cfg.wld_energy_window[1]:
            kwh *= 1.08
    kwh = round(kwh, 3)
    tariff = tariff_for(ts, cfg)

    labor_hours = round(spec.crew * 60 / 60.0, 2)
    return {
        "production": {
            "machine_code": spec.code, "sku": sku, "period_start": ts, "period_end": ts + timedelta(hours=1), "shift": shift,
            "planned_minutes": 60, "planned_downtime_minutes": planned_dt, "unplanned_downtime_minutes": unplanned_dt, "run_minutes": run_min,
            "ideal_cycle_time_sec": round(ideal_cycle, 2), "target_units": target, "units_produced": units, "good_units": good,
            "defective_units": defective, "material_kg_used": material_kg, "labor_hours": labor_hours, "labor_cost": _round_money(labor_hours * WAGE[shift]),
        },
        "energy": {"machine_code": spec.code, "period_start": ts, "kwh": kwh, "tariff_per_kwh": tariff, "energy_cost": _round_money(kwh * tariff)},
        "quality": quality,
        "stops": new_stops,
        "maintenance": new_maint,
    }


def new_machine_states(specs: list[MachineSpec], cfg: SimConfig, rng: np.random.Generator) -> dict[str, MState]:
    start = datetime.combine(cfg.start_date, datetime.min.time())
    return {s.code: MState(last_pm_ts=start - timedelta(days=float(rng.integers(0, 7)))) for s in specs}


def on_gap(st: MState) -> None:
    """Called when the plant was idle (Sunday) since the previous simulated hour."""
    st.stop = None
    st.pending = []
    st.restart_hours = 0


def products_by_sku() -> dict[str, dict]:
    return {p["sku"]: p for p in PRODUCT_DEFS}
