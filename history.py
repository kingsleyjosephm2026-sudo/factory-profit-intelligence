"""Reproducible generation of the SIMULATED 90+ day history and its persistence."""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.version import bump_version, ensure_sim_state
from app.sim import engine as eng
from app.sim.inventory import InventorySim, derive_params

log = logging.getLogger("fpi.sim.history")

CHUNK = 5000


def bulk_insert(session: Session, model, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        session.execute(insert(model), rows[i : i + CHUNK])


def ensure_master_data(session: Session) -> None:
    """Create the fictional factory, lines, machines and products if the factory table is empty."""
    if session.scalar(select(m.Factory.id).limit(1)) is not None:
        return
    f = m.Factory(**eng.PLANT)
    session.add(f)
    session.flush()
    line_ids: dict[str, int] = {}
    for code, name in eng.LINES:
        ln = m.ProductionLine(factory_id=f.id, code=code, name=name)
        session.add(ln)
        session.flush()
        line_ids[code] = ln.id
    for spec in eng.machine_specs():
        session.add(m.Machine(line_id=line_ids[spec.line], code=spec.code, name=spec.name, machine_type=spec.mtype, rated_kw=spec.rated_kw,
                              idle_kw=spec.idle_kw, speed_factor=spec.speed, crew_size=spec.crew))
    for p in eng.PRODUCT_DEFS:
        session.add(m.Product(sku=p["sku"], name=p["name"], category=p["category"], primary_line_code=p["line"], selling_price=p["price"],
                             material_code=p["material"], bom_kg_per_unit=p["bom"], material_cost_per_kg=eng.MATERIALS[p["material"]]["unit_cost"],
                             std_conversion_cost=p["conv"], rework_cost=p["rework"], target_defect_rate_pct=p["target_def"], base_cycle_sec=p["cycle"]))
    session.flush()


def generate_history_data(cfg: eng.SimConfig, seed: int) -> dict[str, Any]:
    """Pure generation (no DB). Returns plain python rows plus the final simulator state."""
    rng = np.random.default_rng(seed)
    specs = eng.machine_specs()
    prods = eng.products_by_sku()
    states = eng.new_machine_states(specs, cfg, rng)
    start_dt = datetime.combine(cfg.start_date, time.min)

    production: list[dict] = []
    energy: list[dict] = []
    quality: list[dict] = []
    stops: list[dict] = []
    maint: list[dict] = []
    prev_idle = False
    for h in range(cfg.days * 24):
        ts = start_dt + timedelta(hours=h)
        if eng.is_idle_hour(ts):
            prev_idle = True
            continue
        if prev_idle:
            for st in states.values():
                eng.on_gap(st)
            prev_idle = False
        for spec in specs:
            r = eng.step_hour(spec, ts, states[spec.code], rng, cfg, prods)
            production.append(r["production"])
            energy.append(r["energy"])
            for q in r["quality"]:
                quality.append({"machine_code": spec.code, "period_start": ts, **q})
            for s in r["stops"]:
                stops.append({"machine_code": spec.code, **s})
            for mt in r["maintenance"]:
                maint.append({"machine_code": spec.code, **mt})

    # daily flows -> inventory
    daily_rm: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    daily_good: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in production:
        d = p["period_start"].date()
        daily_rm[d][prods[p["sku"]]["material"]] += p["material_kg_used"]
        daily_good[d][p["sku"]] += p["good_units"]
    params = derive_params(daily_rm, daily_good, cfg.days)
    inv = InventorySim(params, seed, cfg)
    snapshots: list[dict] = []
    for i in range(cfg.days):
        d = cfg.start_date + timedelta(days=i)
        snapshots.extend(inv.close_day(d, daily_rm.get(d, {}), daily_good.get(d, {})))

    return {
        "production": production, "energy": energy, "quality": quality, "stops": stops, "maintenance": maint, "inventory": snapshots,
        "machine_states": {c: s.to_json() for c, s in states.items()}, "inventory_params": params, "inventory_state": inv.to_json(),
        "history_end": start_dt + timedelta(hours=cfg.days * 24), "last_closed_date": (cfg.start_date + timedelta(days=cfg.days - 1)).isoformat(),
    }


def dataset_fingerprint(data: dict[str, Any]) -> str:
    """Stable hash of the generated history (used by the reproducibility test)."""
    h = hashlib.sha256()
    for key in ("production", "energy", "quality", "stops", "maintenance", "inventory"):
        df = pd.DataFrame(data[key])
        h.update(key.encode())
        h.update(df.to_csv(index=False).encode())
    return h.hexdigest()


def clear_operational_data(session: Session) -> None:
    for model in (m.QualityRecord, m.MaintenanceEvent, m.DowntimeEvent, m.EnergyRecord, m.ProductionRecord, m.InventorySnapshot):
        session.execute(delete(model))


def persist_history(session: Session, data: dict[str, Any], cfg: eng.SimConfig, seed: int) -> dict[str, int]:
    machine_ids = {c: i for c, i in session.execute(select(m.Machine.code, m.Machine.id)).all()}
    product_ids = {c: i for c, i in session.execute(select(m.Product.sku, m.Product.id)).all()}

    prod_rows = []
    for p in data["production"]:
        r = dict(p)
        r["machine_id"] = machine_ids[r.pop("machine_code")]
        r["product_id"] = product_ids[r.pop("sku")]
        r["source"] = "history"
        prod_rows.append(r)
    bulk_insert(session, m.ProductionRecord, prod_rows)

    pid = {(mid, ps): i for i, mid, ps in session.execute(select(m.ProductionRecord.id, m.ProductionRecord.machine_id, m.ProductionRecord.period_start)).all()}
    q_rows = [{"production_record_id": pid[(machine_ids[q["machine_code"]], q["period_start"])], "defect_category": q["defect_category"], "defect_units": q["defect_units"],
               "scrapped_units": q["scrapped_units"], "reworked_units": q["reworked_units"], "source": "history"} for q in data["quality"]]
    bulk_insert(session, m.QualityRecord, q_rows)
    bulk_insert(session, m.EnergyRecord, [{"machine_id": machine_ids[e["machine_code"]], "period_start": e["period_start"], "kwh": e["kwh"], "tariff_per_kwh": e["tariff_per_kwh"],
                                           "energy_cost": e["energy_cost"], "source": "history"} for e in data["energy"]])

    dt_rows = []
    for s in data["stops"]:
        info = m.DOWNTIME_REASONS[s["reason_code"]]
        dt_rows.append({"machine_id": machine_ids[s["machine_code"]], "start_ts": s["start_ts"], "end_ts": s["end_ts"], "duration_minutes": s["duration_minutes"],
                        "planned": s["planned"], "reason_code": s["reason_code"], "reason_category": info["category"], "description": s["description"], "source": "history"})
    bulk_insert(session, m.DowntimeEvent, dt_rows)
    dt_id = {(mid, st, rc): i for i, mid, st, rc in session.execute(select(m.DowntimeEvent.id, m.DowntimeEvent.machine_id, m.DowntimeEvent.start_ts, m.DowntimeEvent.reason_code)).all()}
    mt_rows = []
    for x in data["maintenance"]:
        mid = machine_ids[x["machine_code"]]
        mt_rows.append({"machine_id": mid, "downtime_event_id": dt_id.get((mid, x["link"][0], x["link"][1])), "event_ts": x["event_ts"], "category": x["category"],
                        "description": x["description"], "duration_minutes": x["duration_minutes"], "cost": x["cost"], "planned": x["planned"], "source": "history"})
    bulk_insert(session, m.MaintenanceEvent, mt_rows)

    inv_rows = []
    for s in data["inventory"]:
        r = {k: v for k, v in s.items() if k != "sku"}
        r["product_id"] = product_ids.get(s["sku"]) if s["sku"] else None
        r["source"] = "history"
        inv_rows.append(r)
    bulk_insert(session, m.InventorySnapshot, inv_rows)

    state = ensure_sim_state(session)
    state.running = False
    state.sim_clock = data["history_end"]
    state.history_end = data["history_end"]
    state.tick_count = 0
    state.seed = seed
    state.last_tick_at = None
    state.carry = {"machines": data["machine_states"], "inventory_params": data["inventory_params"], "inventory_state": data["inventory_state"],
                   "last_closed_date": data["last_closed_date"], "cfg_start": cfg.start_date.isoformat(), "cfg_days": cfg.days}
    bump_version(session)
    session.flush()
    return {"production": len(prod_rows), "quality": len(q_rows), "energy": len(data["energy"]), "downtime": len(dt_rows), "maintenance": len(mt_rows), "inventory": len(inv_rows)}
