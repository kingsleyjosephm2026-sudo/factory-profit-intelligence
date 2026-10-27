"""Live-demo simulator. Writes SIMULATED production, downtime, energy and quality rows into the real tables,
so every dashboard metric reacts. It advances a simulated clock (15 simulated minutes per tick) starting right after
the latest record. Rows are tagged source='simulation' and capped by a retention limit; reset removes them."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from .. import models as m
from ..config import Settings, get_settings
from . import datagen

log = logging.getLogger("fpi.simulator")


class Simulator:
    def __init__(self, session_factory: sessionmaker, cfg: Settings | None = None):
        self.sf = session_factory
        self.cfg = cfg or get_settings()
        self.running = False
        self.ticks = 0
        self.clock: datetime | None = None
        self.last_tick_at: datetime | None = None
        self.last_error: str | None = None
        self.version = 0  # increments on every data change so clients know when to refetch
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        self.running = True

    def pause(self) -> None:
        self.running = False

    def reset(self) -> dict:
        self.running = False
        with self.sf() as db:
            ids = list(db.scalars(select(m.ProductionRecord.id).where(m.ProductionRecord.source == "simulation")))
            for model in (m.DowntimeEvent, m.EnergyRecord, m.MaintenanceEvent):
                db.execute(delete(model).where(model.source == "simulation"))
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                db.execute(delete(m.QualityRecord).where(m.QualityRecord.production_record_id.in_(chunk)))
                db.execute(delete(m.ProductionRecord).where(m.ProductionRecord.id.in_(chunk)))
            db.commit()
        self.ticks, self.clock, self.last_error = 0, None, None
        self.version += 1
        return {"removed_production_rows": len(ids)}

    # ------------------------------------------------------------------ one tick (synchronous, testable)
    def tick(self, db: Session | None = None) -> dict:
        own = db is None
        db = db or self.sf()
        try:
            machines = list(db.scalars(select(m.Machine).order_by(m.Machine.id)))
            if not machines:
                raise RuntimeError("No machines loaded; generate demo data first.")
            if self.clock is None:
                last = db.execute(select(m.ProductionRecord.period_start, m.ProductionRecord.period_minutes).order_by(m.ProductionRecord.period_start.desc()).limit(1)).first()
                if last is None:
                    raise RuntimeError("No production data loaded; generate demo data first.")
                ps = last[0] if isinstance(last[0], datetime) else datetime.fromisoformat(str(last[0]))
                self.clock = ps + timedelta(minutes=int(last[1]))
            step = self.cfg.sim_interval_minutes
            rng = np.random.default_rng(self.cfg.seed + 1000 + self.ticks)
            lines = {ln.id: ln for ln in db.scalars(select(m.ProductionLine))}
            products = list(db.scalars(select(m.Product).order_by(m.Product.id)))
            by_line: dict[str, list] = {}
            for p in products:
                for sku, _n, _c, line, *_ in datagen.PRODUCTS:
                    if sku == p.sku:
                        by_line.setdefault(line, []).append(p)
            added = 0
            for mc in machines:
                lc = lines[mc.line_id].code
                plist = by_line.get(lc) or products
                prod = plist[(self.clock.timetuple().tm_yday + mc.id) % len(plist)]
                built = datagen.build_interval(mc, lc, prod, self.clock, step, datagen.shift_of(self.clock), 1.0, rng, [], self.cfg.target_efficiency)
                if db.scalar(select(m.ProductionRecord.id).where(m.ProductionRecord.machine_id == mc.id, m.ProductionRecord.period_start == self.clock)):
                    continue  # never collide with existing data
                datagen.persist_interval(db, mc.id, built, "simulation")
                added += 1
            db.flush()
            self._prune(db)
            db.commit()
            self.clock += timedelta(minutes=step)
            self.ticks += 1
            self.version += 1
            self.last_tick_at = datetime.utcnow()
            self.last_error = None
            return {"added": added, "clock": self.clock.isoformat(), "ticks": self.ticks}
        except Exception as e:  # noqa: BLE001
            db.rollback()
            self.last_error = str(e)
            log.exception("simulation tick failed")
            raise
        finally:
            if own:
                db.close()

    def _prune(self, db: Session) -> int:
        """Retention: keep at most sim_max_rows simulated production rows (oldest removed first)."""
        n = db.scalar(select(func.count()).select_from(m.ProductionRecord).where(m.ProductionRecord.source == "simulation")) or 0
        excess = n - self.cfg.sim_max_rows
        if excess <= 0:
            return 0
        old = db.execute(select(m.ProductionRecord.id, m.ProductionRecord.period_start).where(m.ProductionRecord.source == "simulation")
                         .order_by(m.ProductionRecord.period_start).limit(excess)).all()
        ids = [r[0] for r in old]
        cutoff = max(r[1] if isinstance(r[1], datetime) else datetime.fromisoformat(str(r[1])) for r in old)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            db.execute(delete(m.QualityRecord).where(m.QualityRecord.production_record_id.in_(chunk)))
            db.execute(delete(m.ProductionRecord).where(m.ProductionRecord.id.in_(chunk)))
        for model, col in ((m.DowntimeEvent, m.DowntimeEvent.start_ts), (m.EnergyRecord, m.EnergyRecord.period_start), (m.MaintenanceEvent, m.MaintenanceEvent.event_ts)):
            db.execute(delete(model).where(model.source == "simulation", col <= cutoff))
        return len(ids)

    # ------------------------------------------------------------------ background loop
    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.sim_interval_seconds)
            if not self.running:
                continue
            try:
                async with self._lock:
                    await run_in_threadpool(self.tick)
            except Exception:  # noqa: BLE001 - keep the loop alive; the error is exposed via status
                self.running = False

    def status(self, db: Session) -> dict:
        n = db.scalar(select(func.count()).select_from(m.ProductionRecord).where(m.ProductionRecord.source == "simulation")) or 0
        return dict(
            mode="SIMULATED DEMO DATA", running=self.running, ticks=self.ticks, simulated_clock=self.clock.isoformat() if self.clock else None,
            last_tick_at=self.last_tick_at.isoformat() + "Z" if self.last_tick_at else None, simulated_rows=int(n), retention_limit=self.cfg.sim_max_rows,
            poll_seconds=self.cfg.sim_interval_seconds, minutes_per_tick=self.cfg.sim_interval_minutes, version=self.version, error=self.last_error,
            note="Simulated clock: each tick adds simulated production intervals for every machine. This is not real factory telemetry.",
        )
